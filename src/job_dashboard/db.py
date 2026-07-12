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


def init_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


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
