"""Storage for the Application Agent: the reusable application_profile
(single row) and per-job applications. Kept out of db.py to respect the
500-line cap; init_db calls ensure_application_tables.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

_PROFILE_COLS = (
    "full_name", "email", "phone", "location", "linkedin_url", "github_url",
    "portfolio_url", "work_authorization", "years_experience",
    "willing_to_relocate", "notice_period", "salary_expectation",
    "current_ctc", "reason_for_change",
    "gender", "ethnicity", "veteran_status", "disability_status",
)


def ensure_application_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS application_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            full_name TEXT, email TEXT, phone TEXT, location TEXT,
            linkedin_url TEXT, github_url TEXT, portfolio_url TEXT,
            work_authorization TEXT, years_experience TEXT,
            willing_to_relocate INTEGER, notice_period TEXT,
            salary_expectation TEXT, current_ctc TEXT, reason_for_change TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            resume_id INTEGER, cover_letter_id INTEGER,
            status TEXT NOT NULL DEFAULT 'prepared',
            screening TEXT, ats TEXT,
            applied_at TEXT, created_at TEXT NOT NULL
        )
    """)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(application_profile)")}
    for col in _PROFILE_COLS:          # additive migration for any new profile column
        if col not in existing:
            conn.execute(f"ALTER TABLE application_profile ADD COLUMN {col} TEXT")


def get_application_profile(conn):
    row = conn.execute(
        "SELECT " + ", ".join(_PROFILE_COLS) + ", updated_at "
        "FROM application_profile WHERE id = 1").fetchone()
    if row is None:
        return None
    d = dict(zip(_PROFILE_COLS + ("updated_at",), row))
    d["willing_to_relocate"] = bool(d["willing_to_relocate"]) if d["willing_to_relocate"] is not None else None
    return d


def save_application_profile(conn, fields):
    now = datetime.now(timezone.utc).isoformat()
    vals = {k: fields.get(k) for k in _PROFILE_COLS}
    if vals.get("willing_to_relocate") is not None:
        vals["willing_to_relocate"] = 1 if vals["willing_to_relocate"] else 0
    cols = list(_PROFILE_COLS)
    placeholders = ", ".join(["?"] * (len(cols) + 1))
    conn.execute(
        f"INSERT INTO application_profile (id, {', '.join(cols)}, updated_at) "
        f"VALUES (1, {', '.join(['?'] * len(cols))}, ?) "
        f"ON CONFLICT(id) DO UPDATE SET "
        + ", ".join(f"{c}=excluded.{c}" for c in cols) + ", updated_at=excluded.updated_at",
        tuple(vals[c] for c in cols) + (now,),
    )
    conn.commit()
    return get_application_profile(conn)


def save_application(conn, job_id, resume_id=None, cover_letter_id=None,
                     screening=None, ats=None, status="prepared"):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO applications
               (job_id, resume_id, cover_letter_id, status, screening, ats, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (job_id, resume_id, cover_letter_id, status,
         json.dumps(screening or []), ats, now),
    )
    conn.commit()
    return conn.execute("SELECT id FROM applications ORDER BY id DESC LIMIT 1").fetchone()[0]


def get_application(conn, job_id):
    row = conn.execute(
        """SELECT id, job_id, resume_id, cover_letter_id, status, screening, ats,
                  applied_at, created_at
           FROM applications WHERE job_id = ? ORDER BY id DESC LIMIT 1""",
        (job_id,)).fetchone()
    if row is None:
        return None
    keys = ("id", "job_id", "resume_id", "cover_letter_id", "status", "screening",
            "ats", "applied_at", "created_at")
    d = dict(zip(keys, row))
    d["screening"] = json.loads(d["screening"]) if d["screening"] else []
    return d


def set_application_status(conn, application_id, status, applied_at=None):
    conn.execute("UPDATE applications SET status = ?, applied_at = ? WHERE id = ?",
                 (status, applied_at, application_id))
    conn.commit()
