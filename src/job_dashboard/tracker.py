"""The application tracker: which tracked job is in which status, why a failed
one stopped (its apply-queue reason), and which interview round it reached.

Statuses live in jobs.status (see db.VALID_STATUSES): saved (queued), applied,
failed, interviewing (+ interview_round), offer (selected), rejected. Kept out
of db.py for its 500-line cap; init_db calls ensure().
"""
from __future__ import annotations

import re

from job_dashboard import paths
from job_dashboard.db import set_job_status

TRACKED = ("saved", "applied", "failed", "interviewing", "offer", "rejected")
_KEYS = ("id", "title", "company", "location", "source", "status", "embed_score", "llm_score", "verdict",
         "industry", "company_type", "interview_round", "queue_state", "queue_reason")


_ERROR_LINE = re.compile(r"^(?:[\w.]+\.)?(\w*(?:Error|Exception))\b:?\s*(.*)$")


def last_error(job_id) -> str | None:
    """The final exception line of a job's agent log ("could not attach to the agent browser: ..."), so a failed row
    says what actually happened instead of just "agent error"."""
    path = paths.AGENT_RUNS / f"{job_id}.log"
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 16384))
            lines = f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        m = _ERROR_LINE.match(line.strip())
        if m and m.group(2):
            msg = m.group(2).strip()
            return msg if len(msg) <= 240 else msg[:240] + "…"
    return None


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
        if d["status"] == "failed":
            d["error_detail"] = last_error(d["id"])
        buckets["archived" if d["status"] == "rejected" else d["status"]].append(d)
    return buckets
