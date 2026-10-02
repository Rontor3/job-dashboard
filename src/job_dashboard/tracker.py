"""The application tracker: which tracked job is in which status, why a failed
one stopped (its apply-queue reason), and which interview round it reached.

Statuses live in jobs.status (see db.VALID_STATUSES): saved (queued), applied,
failed, interviewing (+ interview_round), offer (selected), rejected. Kept out
of db.py for its 500-line cap; init_db calls ensure().
"""
from __future__ import annotations

from job_dashboard.db import set_job_status

TRACKED = ("saved", "applied", "failed", "interviewing", "offer", "rejected")
_KEYS = ("id", "title", "company", "location", "source", "status", "embed_score", "llm_score", "verdict",
         "industry", "company_type", "interview_round", "queue_state", "queue_reason")


def ensure(conn) -> None:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()]
    if "interview_round" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN interview_round INTEGER")


def set_status(conn, job_id, status, round=None) -> None:
    """set_job_status + the interview round: 1 unless given while interviewing,
    cleared for every other status."""
    if round is not None and (not isinstance(round, int) or round < 1):
        raise ValueError("round must be a positive integer")
    set_job_status(conn, job_id, status)
    conn.execute("UPDATE jobs SET interview_round = ? WHERE id = ?",
                 ((round or 1) if status == "interviewing" else None, job_id))
    conn.commit()


def tracker_jobs(conn) -> dict:
    marks = ",".join("?" * len(TRACKED))
    rows = conn.execute(
        f"""SELECT j.id, j.title, j.company, j.location, j.source, j.status,
                  m.embed_score, m.llm_score, m.verdict, cc.industry, cc.company_type,
                  j.interview_round, aq.state, aq.reason
           FROM jobs j
           LEFT JOIN match_scores m ON m.job_id = j.id
           LEFT JOIN company_classifications cc ON cc.company_key = LOWER(TRIM(j.company))
           LEFT JOIN apply_queue aq ON aq.job_id = j.id
           WHERE j.duplicate_of IS NULL AND j.status IN ({marks})
           ORDER BY j.status_updated_at IS NULL, j.status_updated_at DESC, j.id DESC""",
        TRACKED).fetchall()
    buckets = {"saved": [], "applied": [], "failed": [], "interviewing": [], "offer": [], "archived": []}
    for r in rows:
        d = dict(zip(_KEYS, r))
        buckets["archived" if d["status"] == "rejected" else d["status"]].append(d)
    return buckets
