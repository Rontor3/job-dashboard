"""What holds for every opening at a company: who referred you, a relative there, applied / interviewed / worked
there before. Entered once per company on the Jobs tab; a job's own details (jobs.apply_details) win where set.

    get(conn, company) -> dict          put(conn, company, details)          every(conn) -> {key: {company, details}}
    merged(company, job) -> dict        the details the apply agent sees (db.get_job)

Writes go through the change log as entity "company" (change_entities.py), so each has an Undo.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

FIELDS = ("referrer", "relatives", "applied_before", "interviewed_before", "worked_before")

_SQL = """CREATE TABLE IF NOT EXISTS company_details (
    company_key TEXT PRIMARY KEY, company TEXT NOT NULL, details TEXT NOT NULL, updated_at TEXT NOT NULL)"""


def key(company: str | None) -> str:
    return " ".join((company or "").lower().split())


def ensure(conn) -> None:
    conn.execute(_SQL)


def get(conn, company: str | None) -> dict:
    try:
        row = conn.execute("SELECT details FROM company_details WHERE company_key=?", (key(company),)).fetchone()
    except sqlite3.OperationalError:                       # an older or partial database: nothing entered yet
        return {}
    return json.loads(row[0]) if row else {}


def put(conn, company: str, details: dict | None) -> None:
    """Save (or, when nothing is set, clear) a company's details."""
    ensure(conn)
    kept = {k: v for k, v in (details or {}).items() if k in FIELDS and v not in (None, "", False)}
    if not kept:
        conn.execute("DELETE FROM company_details WHERE company_key=?", (key(company),))
    else:
        conn.execute(
            "INSERT INTO company_details (company_key, company, details, updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(company_key) DO UPDATE SET company=excluded.company, details=excluded.details, "
            "updated_at=excluded.updated_at",
            (key(company), company.strip(), json.dumps(kept), datetime.now(timezone.utc).isoformat()))
    conn.commit()


def every(conn) -> dict[str, dict]:
    ensure(conn)
    return {k: {"company": c, "details": json.loads(d)}
            for k, c, d in conn.execute("SELECT company_key, company, details FROM company_details")}


def merged(company: dict, job: dict) -> dict:
    """The job's own details, with the company's filling whatever the job leaves unset."""
    out = dict(job or {})
    for k, v in (company or {}).items():
        if not out.get(k):
            out[k] = v
    return out
