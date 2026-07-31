"""Storage for job-associated artifacts: resumes, cover letters, and
company resources (scraped links selected for use in generated documents).

Extracted from db.py verbatim (move-only refactor; no behavior change).
"""

import json
import re
import sqlite3
from datetime import datetime, timezone


def _ensure_resumes_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS resumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            pdf_path TEXT,
            blocks_used TEXT,
            ats_score REAL,
            ats_report TEXT,
            created_at TEXT NOT NULL
        )
    """)


def save_resume(conn, job_id, pdf_path, blocks_used, ats_score, ats_report):
    """Save a resume for a job. Returns the new resume id."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO resumes (job_id, pdf_path, blocks_used, ats_score, ats_report, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (job_id, pdf_path, json.dumps(blocks_used), ats_score, json.dumps(ats_report), now),
    )
    conn.commit()
    return conn.execute("SELECT id FROM resumes ORDER BY id DESC LIMIT 1").fetchone()[0]


def resumes_for_job(conn, job_id):
    """Get all resumes for a job, newest first. Returns list of dicts with parsed JSON."""
    rows = conn.execute(
        """SELECT id, job_id, pdf_path, blocks_used, ats_score, ats_report, created_at
           FROM resumes WHERE job_id = ? ORDER BY created_at DESC""",
        (job_id,),
    ).fetchall()
    keys = ("id", "job_id", "pdf_path", "blocks_used", "ats_score", "ats_report", "created_at")
    result = []
    for row in rows:
        d = dict(zip(keys, row))
        d["blocks_used"] = json.loads(d["blocks_used"]) if d["blocks_used"] else []
        d["ats_report"] = json.loads(d["ats_report"]) if d["ats_report"] else {}
        result.append(d)
    return result


def get_resume(conn, resume_id):
    """Get a single resume by id. Returns dict with parsed JSON or None."""
    row = conn.execute(
        """SELECT id, job_id, pdf_path, blocks_used, ats_score, ats_report, created_at
           FROM resumes WHERE id = ?""",
        (resume_id,),
    ).fetchone()
    if row is None:
        return None
    keys = ("id", "job_id", "pdf_path", "blocks_used", "ats_score", "ats_report", "created_at")
    d = dict(zip(keys, row))
    d["blocks_used"] = json.loads(d["blocks_used"]) if d["blocks_used"] else []
    d["ats_report"] = json.loads(d["ats_report"]) if d["ats_report"] else {}
    return d


def _ensure_cover_letters_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cover_letters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            pdf_path TEXT,
            body TEXT,
            company_facts_used TEXT,
            created_at TEXT NOT NULL
        )
    """)


def save_cover_letter(conn, job_id, pdf_path, body, company_facts_used):
    """Save a cover letter for a job. Returns the new cover letter id."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO cover_letters (job_id, pdf_path, body, company_facts_used, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (job_id, pdf_path, body, json.dumps(company_facts_used), now),
    )
    conn.commit()
    return conn.execute("SELECT id FROM cover_letters ORDER BY id DESC LIMIT 1").fetchone()[0]


def cover_letters_for_job(conn, job_id):
    """Get all cover letters for a job, newest first. Returns list of dicts with parsed JSON."""
    rows = conn.execute(
        """SELECT id, job_id, pdf_path, body, company_facts_used, created_at
           FROM cover_letters WHERE job_id = ? ORDER BY created_at DESC""",
        (job_id,),
    ).fetchall()
    keys = ("id", "job_id", "pdf_path", "body", "company_facts_used", "created_at")
    result = []
    for row in rows:
        d = dict(zip(keys, row))
        d["company_facts_used"] = json.loads(d["company_facts_used"]) if d["company_facts_used"] else []
        result.append(d)
    return result


def get_cover_letter(conn, cover_letter_id):
    """Get a single cover letter by id. Returns dict with parsed JSON or None."""
    row = conn.execute(
        """SELECT id, job_id, pdf_path, body, company_facts_used, created_at
           FROM cover_letters WHERE id = ?""",
        (cover_letter_id,),
    ).fetchone()
    if row is None:
        return None
    keys = ("id", "job_id", "pdf_path", "body", "company_facts_used", "created_at")
    d = dict(zip(keys, row))
    d["company_facts_used"] = json.loads(d["company_facts_used"]) if d["company_facts_used"] else []
    return d


_COMPANY_SUFFIX_RE = re.compile(r"\b(inc|llc|ltd|corp|co)\.?$")


def company_key(company):
    key = " ".join((company or "").split()).strip().lower()
    return _COMPANY_SUFFIX_RE.sub("", key).strip()


def _ensure_company_resources_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS company_resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_key TEXT NOT NULL,
            source_url TEXT NOT NULL,
            title TEXT,
            summary TEXT,
            selected INTEGER NOT NULL DEFAULT 0,
            rank INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE (company_key, source_url)
        )
    """)
    # Idempotent add for tables created before `rank` existed.
    try:
        conn.execute("ALTER TABLE company_resources ADD COLUMN rank INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already present


def upsert_company_resources(conn, company_key, resources):
    # Empty company_key would pool every unnamed-company job into one shared
    # bucket (cross-job leak) -- refuse to store for a company we can't key.
    if not company_key:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for rank, r in enumerate(resources):
        conn.execute(
            """INSERT INTO company_resources
                   (company_key, source_url, title, summary, selected, rank, created_at)
               VALUES (?, ?, ?, ?, 0, ?, ?)
               ON CONFLICT(company_key, source_url)
               DO UPDATE SET title=excluded.title, summary=excluded.summary,
                             rank=excluded.rank""",
            (company_key, r["source_url"], r.get("title"), r.get("summary"), rank, now),
        )
        n += 1
    conn.commit()
    return n


def _resource_rows(conn, company_key, selected_only=False):
    if not company_key:
        return []
    q = ("SELECT id, company_key, source_url, title, summary, selected, created_at "
         "FROM company_resources WHERE company_key = ?")
    if selected_only:
        q += " AND selected = 1"
    # Rank ASC = best-first (the order resources_from_bundle produced), so the
    # draft's no-pick "top-2" fallback and the UI card list both surface the
    # strongest sources first -- NOT reverse-insertion order.
    q += " ORDER BY rank ASC, id ASC"
    keys = ("id", "company_key", "source_url", "title", "summary", "selected", "created_at")
    out = []
    for row in conn.execute(q, (company_key,)).fetchall():
        d = dict(zip(keys, row))
        d["selected"] = bool(d["selected"])
        out.append(d)
    return out


def company_resources_for(conn, company_key):
    return _resource_rows(conn, company_key)


def selected_resources_for(conn, company_key):
    return _resource_rows(conn, company_key, selected_only=True)


def set_selected_resources(conn, company_key, source_urls):
    if not company_key:
        return
    conn.execute("UPDATE company_resources SET selected = 0 WHERE company_key = ?",
                 (company_key,))
    existing = {r["source_url"] for r in company_resources_for(conn, company_key)}
    chosen = [u for u in source_urls if u in existing][:2]
    for u in chosen:
        conn.execute(
            "UPDATE company_resources SET selected = 1 WHERE company_key = ? AND source_url = ?",
            (company_key, u),
        )
    conn.commit()
