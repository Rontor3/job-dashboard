import json
import re
import sqlite3
from datetime import datetime, timezone, timedelta

from job_dashboard.models import Company, JobListing
from job_dashboard.artifacts_store import (
    _ensure_resumes_table,
    save_resume,
    resumes_for_job,
    get_resume,
    _ensure_cover_letters_table,
    save_cover_letter,
    cover_letters_for_job,
    get_cover_letter,
    company_key,
    _ensure_company_resources_table,
    upsert_company_resources,
    company_resources_for,
    selected_resources_for,
    set_selected_resources,
)
from job_dashboard.db_hiring import (  # noqa: F401 — re-exported for callers
    _ensure_hiring_posts_table,
    upsert_hiring_post,
    hiring_posts,
    dismiss_hiring_post,
)

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
VALID_STATUSES = {"saved", "applied", "interviewing", "offer", "rejected", "dismissed"}


def init_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executescript(MATCH_SCHEMA)
    _ensure_duplicate_of_column(conn)
    _ensure_status_column(conn)
    _ensure_resumes_table(conn)
    _ensure_cover_letters_table(conn)
    _ensure_company_resources_table(conn)
    _ensure_company_classifications_table(conn)
    _ensure_hiring_posts_table(conn)
    from job_dashboard.apply.store import ensure_application_tables
    ensure_application_tables(conn)
    conn.commit()
    return conn


def _ensure_duplicate_of_column(conn):
    cols = [row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()]
    if "duplicate_of" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN duplicate_of INTEGER")


def _ensure_status_column(conn):
    cols = [row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()]
    if "status" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN status TEXT")


def _ensure_company_classifications_table(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS company_classifications (
               company_key  TEXT PRIMARY KEY,
               industry     TEXT NOT NULL,
               company_type TEXT NOT NULL,
               method       TEXT NOT NULL,
               updated_at   TEXT NOT NULL
           )"""
    )


def upsert_company_classification(conn, company_key, industry, company_type, method):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO company_classifications
               (company_key, industry, company_type, method, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(company_key) DO UPDATE SET
               industry=excluded.industry, company_type=excluded.company_type,
               method=excluded.method, updated_at=excluded.updated_at""",
        (company_key, industry, company_type, method, now),
    )
    conn.commit()


def get_company_classification(conn, company_key):
    row = conn.execute(
        "SELECT company_key, industry, company_type, method, updated_at "
        "FROM company_classifications WHERE company_key = ?", (company_key,)).fetchone()
    if row is None:
        return None
    return dict(zip(("company_key", "industry", "company_type", "method", "updated_at"), row))


def unclassified_companies(conn):
    rows = conn.execute(
        """SELECT DISTINCT LOWER(TRIM(j.company)) k
           FROM jobs j
           WHERE j.duplicate_of IS NULL AND j.company IS NOT NULL AND TRIM(j.company) != ''
             AND LOWER(TRIM(j.company)) NOT IN (SELECT company_key FROM company_classifications)
           ORDER BY k""").fetchall()
    return [r[0] for r in rows]


def distinct_classification_values(conn):
    inds = [r[0] for r in conn.execute(
        "SELECT DISTINCT industry FROM company_classifications ORDER BY industry")]
    types = [r[0] for r in conn.execute(
        "SELECT DISTINCT company_type FROM company_classifications ORDER BY company_type")]
    return {"industries": inds, "company_types": types}


def distinct_sources(conn):
    """Sources actually present in the (canonical) feed — for the Source filter."""
    return [r[0] for r in conn.execute(
        """SELECT DISTINCT source FROM jobs
           WHERE duplicate_of IS NULL AND source IS NOT NULL AND source != ''
           ORDER BY source""")]


def get_sample_job_for_company(conn, company_key):
    """One representative (title, description, display_company) for a company key."""
    row = conn.execute(
        """SELECT title, description, company FROM jobs
           WHERE LOWER(TRIM(company)) = ? AND duplicate_of IS NULL
           ORDER BY id LIMIT 1""", (company_key,)).fetchone()
    return (row[0], row[1], row[2]) if row else ("", "", company_key)


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


def set_job_status(conn, job_id, status):
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {sorted(VALID_STATUSES)} or None, got {status!r}")
    cur = conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
    conn.commit()
    if cur.rowcount == 0:
        raise KeyError(f"no job with id {job_id}")


_JOB_COLUMNS = ("id", "title", "company", "location", "job_url", "job_type",
                "is_remote", "posted_date", "source", "status",
                "embed_score", "llm_score", "verdict")


def query_jobs(conn, q=None, remote=None, job_type=None, source=None, industry=None, company_type=None, status=None,
               verdict=None, min_score=None, include_dismissed=False, sort="embed",
               limit=50, offset=0):
    where = ["j.duplicate_of IS NULL"]
    params = []
    if verdict:
        where.append("m.verdict = ?")
        params.append(verdict)
    if q:
        where.append("(LOWER(j.title) LIKE ? OR LOWER(j.company) LIKE ?)")
        needle = f"%{q.lower()}%"
        params += [needle, needle]
    if remote is not None:
        where.append("j.is_remote = ?")
        params.append(int(remote))
    if job_type:
        where.append("REPLACE(LOWER(j.job_type), '_', '') = ?")
        params.append(job_type.lower().replace("_", ""))
    if source:
        where.append("j.source = ?")
        params.append(source)
    if industry:
        where.append("cc.industry = ?")
        params.append(industry)
    if company_type:
        where.append("cc.company_type = ?")
        params.append(company_type)
    if status:
        where.append("j.status = ?")
        params.append(status)
    elif not include_dismissed:
        where.append("(j.status IS NULL OR j.status != 'dismissed')")
    if min_score is not None:
        where.append("m.embed_score >= ?")
        params.append(min_score)

    order = {
        "embed": "m.embed_score IS NULL, m.embed_score DESC, j.id",
        "llm": "m.llm_score IS NULL, m.llm_score DESC, j.id",
        "date": "j.posted_date IS NULL, j.posted_date DESC, j.id",
    }.get(sort, "m.embed_score IS NULL, m.embed_score DESC, j.id")

    base = f"""FROM jobs j
               LEFT JOIN match_scores m ON m.job_id = j.id
               LEFT JOIN company_classifications cc
                      ON cc.company_key = LOWER(TRIM(j.company))
               WHERE {' AND '.join(where)}"""
    total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT j.id, j.title, j.company, j.location, j.job_url, j.job_type,
                   j.is_remote, j.posted_date, j.source, j.status,
                   m.embed_score, m.llm_score, m.verdict,
                   cc.industry, cc.company_type
            {base} ORDER BY {order} LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    return [dict(zip(_JOB_COLUMNS + ("industry", "company_type"), row)) for row in rows], total


def job_detail(conn, job_id):
    row = conn.execute(
        """SELECT j.id, j.title, j.company, j.location, j.job_url, j.job_type,
                  j.is_remote, j.posted_date, j.source, j.status,
                  m.embed_score, m.llm_score, m.verdict,
                  cc.industry, cc.company_type,
                  j.description, m.strengths, m.gaps, m.flags
           FROM jobs j LEFT JOIN match_scores m ON m.job_id = j.id
           LEFT JOIN company_classifications cc
                  ON cc.company_key = LOWER(TRIM(j.company))
           WHERE j.id = ?""",
        (job_id,),
    ).fetchone()
    if row is None:
        return None
    detail = dict(zip(_JOB_COLUMNS + ("industry", "company_type", "description", "strengths", "gaps", "flags"), row))
    detail["strengths"] = json.loads(detail["strengths"]) if detail["strengths"] else []
    detail["gaps"] = json.loads(detail["gaps"]) if detail["gaps"] else []
    detail["flags"] = json.loads(detail["flags"]) if detail["flags"] else {}
    detail["cross_listings"] = [
        {"id": r[0], "source": r[1], "job_url": r[2]}
        for r in conn.execute(
            "SELECT id, source, job_url FROM jobs WHERE duplicate_of = ? ORDER BY id",
            (job_id,),
        ).fetchall()
    ]
    return detail


def tracker_jobs(conn):
    rows = conn.execute(
        """SELECT j.id, j.title, j.company, j.location, j.source, j.status,
                  m.embed_score, m.llm_score, m.verdict, cc.industry, cc.company_type
           FROM jobs j
           LEFT JOIN match_scores m ON m.job_id = j.id
           LEFT JOIN company_classifications cc ON cc.company_key = LOWER(TRIM(j.company))
           WHERE j.duplicate_of IS NULL
             AND j.status IN ('saved','applied','interviewing','offer','rejected')
           ORDER BY j.id DESC""").fetchall()
    keys = ("id","title","company","location","source","status","embed_score",
            "llm_score","verdict","industry","company_type")
    buckets = {"saved": [], "applied": [], "interviewing": [], "offer": [], "archived": []}
    for r in rows:
        d = dict(zip(keys, r))
        buckets["archived" if d["status"] == "rejected" else d["status"]].append(d)
    return buckets


def dashboard_stats(conn):
    def one(sql, *params):
        return conn.execute(sql, params).fetchone()[0]

    canonical = "FROM jobs WHERE duplicate_of IS NULL"
    return {
        "total": one(f"SELECT COUNT(*) {canonical}"),
        "new": one(f"SELECT COUNT(*) {canonical} AND status IS NULL"),
        "saved": one(f"SELECT COUNT(*) {canonical} AND status = 'saved'"),
        "applied": one(f"SELECT COUNT(*) {canonical} AND status = 'applied'"),
        "interviewing": one(f"SELECT COUNT(*) {canonical} AND status = 'interviewing'"),
        "offer": one(f"SELECT COUNT(*) {canonical} AND status = 'offer'"),
        "rejected": one(f"SELECT COUNT(*) {canonical} AND status = 'rejected'"),
        "dismissed": one(f"SELECT COUNT(*) {canonical} AND status = 'dismissed'"),
        "unranked": one(
            """SELECT COUNT(*) FROM jobs j LEFT JOIN match_scores m ON m.job_id = j.id
               WHERE j.duplicate_of IS NULL AND m.llm_score IS NULL"""
        ),
        "verdict_counts": {
            r[0]: r[1] for r in conn.execute(
                """SELECT m.verdict, COUNT(*) FROM jobs j JOIN match_scores m ON m.job_id = j.id
                   WHERE j.duplicate_of IS NULL AND m.verdict IS NOT NULL GROUP BY m.verdict""")
        },
        "top_industries": [
            {"industry": r[0], "count": r[1]} for r in conn.execute(
                """SELECT cc.industry, COUNT(*) n FROM jobs j
                   JOIN company_classifications cc ON cc.company_key = LOWER(TRIM(j.company))
                   WHERE j.duplicate_of IS NULL GROUP BY cc.industry ORDER BY n DESC LIMIT 6""")
        ],
    }
