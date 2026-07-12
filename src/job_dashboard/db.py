import json
import sqlite3
from datetime import datetime, timezone

from job_dashboard.models import Company, JobListing

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    description TEXT NOT NULL,
    job_url TEXT NOT NULL UNIQUE,
    job_type TEXT,
    is_remote INTEGER,
    salary_text TEXT,
    posted_date TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    funding_amount TEXT,
    funding_round TEXT,
    sector TEXT,
    hq TEXT,
    founders TEXT,
    source TEXT,
    contact_email TEXT,
    contact_source TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
"""

MATCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS match_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL UNIQUE,
    embed_score REAL NOT NULL,
    profile_hash TEXT NOT NULL,
    llm_score INTEGER,
    verdict TEXT,
    strengths TEXT,
    gaps TEXT,
    flags TEXT,
    scored_at TEXT NOT NULL,
    llm_scored_at TEXT
);
"""

VALID_VERDICTS = {"Strong Fit", "Good Fit", "Moderate Fit", "Weak Fit", "Poor Fit"}


def init_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executescript(MATCH_SCHEMA)
    _ensure_duplicate_of_column(conn)
    conn.commit()
    return conn


def _ensure_duplicate_of_column(conn):
    cols = [row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()]
    if "duplicate_of" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN duplicate_of INTEGER")


def job_exists(conn, job_url):
    row = conn.execute("SELECT 1 FROM jobs WHERE job_url = ?", (job_url,)).fetchone()
    return row is not None


# Columns declared NOT NULL in the jobs schema — a listing missing any of
# these can't be stored, so it's skipped at this boundary rather than raising
# sqlite3.IntegrityError mid-ingest.
_REQUIRED_JOB_FIELDS = ("source", "title", "company", "description", "job_url")


def insert_job(conn, job: JobListing):
    for field in _REQUIRED_JOB_FIELDS:
        value = getattr(job, field)
        if value is None or not str(value).strip():
            return False
    if job_exists(conn, job.job_url):
        return False
    conn.execute(
        """INSERT INTO jobs
           (source, external_id, title, company, location, description,
            job_url, job_type, is_remote, salary_text, posted_date, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job.source, job.external_id, job.title, job.company, job.location,
            job.description, job.job_url, job.job_type,
            int(job.is_remote) if job.is_remote is not None else None,
            job.salary_text, job.posted_date,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    return True


def upsert_company(conn, company: Company):
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT id FROM companies WHERE name = ?", (company.name,)
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE companies SET funding_amount = ?, funding_round = ?,
               sector = ?, hq = ?, founders = ?, last_seen_at = ?
               WHERE name = ?""",
            (company.funding_amount, company.funding_round, company.sector,
             company.hq, company.founders, now, company.name),
        )
    else:
        conn.execute(
            """INSERT INTO companies
               (name, funding_amount, funding_round, sector, hq, founders,
                source, first_seen_at, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (company.name, company.funding_amount, company.funding_round,
             company.sector, company.hq, company.founders, company.source,
             now, now),
        )
    conn.commit()


def upsert_embed_score(conn, job_id, embed_score, profile_hash):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO match_scores (job_id, embed_score, profile_hash, scored_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(job_id) DO UPDATE SET
             embed_score = excluded.embed_score,
             profile_hash = excluded.profile_hash,
             scored_at = excluded.scored_at,
             llm_score = NULL, verdict = NULL, strengths = NULL,
             gaps = NULL, flags = NULL, llm_scored_at = NULL""",
        (job_id, embed_score, profile_hash, now),
    )
    conn.commit()


def jobs_needing_embed_score(conn, profile_hash):
    return conn.execute(
        """SELECT j.id, j.description FROM jobs j
           LEFT JOIN match_scores m ON m.job_id = j.id
           WHERE j.duplicate_of IS NULL
             AND (m.job_id IS NULL OR m.profile_hash != ?)
           ORDER BY j.id""",
        (profile_hash,),
    ).fetchall()


def record_llm_evaluation(conn, job_id, llm_score, verdict, strengths, gaps, flags):
    if not isinstance(llm_score, int) or not 0 <= llm_score <= 100:
        raise ValueError(f"llm_score must be an int 0-100, got {llm_score!r}")
    if verdict not in VALID_VERDICTS:
        raise ValueError(f"verdict must be one of {sorted(VALID_VERDICTS)}, got {verdict!r}")
    existing = conn.execute(
        "SELECT 1 FROM match_scores WHERE job_id = ?", (job_id,)
    ).fetchone()
    if existing is None:
        raise ValueError(f"job {job_id} has no embed score yet; run the pipeline first")
    conn.execute(
        """UPDATE match_scores
           SET llm_score = ?, verdict = ?, strengths = ?, gaps = ?, flags = ?,
               llm_scored_at = ?
           WHERE job_id = ?""",
        (llm_score, verdict, json.dumps(strengths), json.dumps(gaps),
         json.dumps(flags), datetime.now(timezone.utc).isoformat(), job_id),
    )
    conn.commit()


def top_unranked_jobs(conn, limit=30):
    rows = conn.execute(
        """SELECT j.id, j.title, j.company, j.location, j.job_url, j.description,
                  m.embed_score
           FROM jobs j JOIN match_scores m ON m.job_id = j.id
           WHERE j.duplicate_of IS NULL AND m.llm_score IS NULL
           ORDER BY m.embed_score DESC, j.id
           LIMIT ?""",
        (limit,),
    ).fetchall()
    keys = ("id", "title", "company", "location", "job_url", "description", "embed_score")
    return [dict(zip(keys, row)) for row in rows]


def canonical_jobs_for_dedup(conn):
    return conn.execute(
        """SELECT id, company, title, fetched_at, source FROM jobs
           WHERE duplicate_of IS NULL
           ORDER BY fetched_at, id"""
    ).fetchall()


def mark_duplicate(conn, job_id, canonical_id):
    conn.execute("UPDATE jobs SET duplicate_of = ? WHERE id = ?", (canonical_id, job_id))
    conn.commit()


def suspected_duplicates(conn):
    rows = conn.execute(
        """SELECT d.id, d.title, d.company, d.source, d.job_url, d.duplicate_of,
                  c.source
           FROM jobs d JOIN jobs c ON c.id = d.duplicate_of
           WHERE d.duplicate_of IS NOT NULL
           ORDER BY d.id"""
    ).fetchall()
    keys = ("id", "title", "company", "source", "job_url", "duplicate_of",
            "canonical_source")
    return [dict(zip(keys, row)) for row in rows]
