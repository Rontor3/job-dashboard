"""The apply queue: jobs waiting to be filled by career_agent, in the order the
human added them. One row per job; the runner (queue_runner.py) moves a row
through queued -> running -> done | parked | failed. Position is a float so a
reorder is a single UPDATE. init_db calls ensure().
"""
from __future__ import annotations

from datetime import datetime, timezone

STATES = ("queued", "running", "parked", "done", "failed")
_FINISHED = ("parked", "done", "failed")


def ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS apply_queue (
        job_id INTEGER PRIMARY KEY,
        position REAL NOT NULL,
        state TEXT NOT NULL DEFAULT 'queued',
        reason TEXT,
        added_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT)""")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _edge(conn, front: bool) -> float:
    agg = "MIN" if front else "MAX"
    row = conn.execute(f"SELECT {agg}(position) FROM apply_queue").fetchone()
    if row[0] is None:
        return 0.0
    return row[0] - 1 if front else row[0] + 1


def enqueue(conn, job_id: int, front: bool = False) -> None:
    """Add a job (or put a finished one back) as queued. A job already queued
    or running keeps its place unless `front` asks to jump it to the head."""
    row = conn.execute("SELECT state FROM apply_queue WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO apply_queue (job_id, position, state, added_at) VALUES (?,?,?,?)",
                     (job_id, _edge(conn, front), "queued", _now()))
    elif row[0] in _FINISHED or front:
        state = "running" if row[0] == "running" else "queued"
        conn.execute("""UPDATE apply_queue SET position = ?, state = ?, reason = NULL,
                        started_at = CASE WHEN ? = 'running' THEN started_at END, finished_at = NULL
                        WHERE job_id = ?""", (_edge(conn, front), state, state, job_id))
    conn.commit()


def remove(conn, job_id: int) -> None:
    conn.execute("DELETE FROM apply_queue WHERE job_id = ?", (job_id,))
    conn.commit()


def move(conn, job_id: int, before: int | None) -> None:
    """Place `job_id` just before `before`, or at the end when `before` is None."""
    if before is None:
        pos = _edge(conn, front=False)
    else:
        target = conn.execute("SELECT position FROM apply_queue WHERE job_id = ?", (before,)).fetchone()
        if target is None:
            raise KeyError(before)
        prev = conn.execute("SELECT MAX(position) FROM apply_queue WHERE position < ? AND job_id != ?",
                            (target[0], job_id)).fetchone()[0]
        pos = target[0] - 1 if prev is None else (prev + target[0]) / 2
    conn.execute("UPDATE apply_queue SET position = ? WHERE job_id = ?", (pos, job_id))
    conn.commit()


def mark(conn, job_id: int, state: str, reason: str | None = None) -> None:
    if state not in STATES:
        raise ValueError(f"unknown queue state {state!r}")
    if state == "running":
        conn.execute("UPDATE apply_queue SET state = ?, reason = NULL, started_at = ?, finished_at = NULL"
                     " WHERE job_id = ?", (state, _now(), job_id))
    elif state in _FINISHED:
        conn.execute("UPDATE apply_queue SET state = ?, reason = ?, finished_at = ? WHERE job_id = ?",
                     (state, reason, _now(), job_id))
    else:
        conn.execute("UPDATE apply_queue SET state = ?, reason = ? WHERE job_id = ?", (state, reason, job_id))
    conn.commit()


def next_queued(conn) -> int | None:
    row = conn.execute("SELECT job_id FROM apply_queue WHERE state = 'queued'"
                       " ORDER BY position LIMIT 1").fetchone()
    return row[0] if row else None


def list_queue(conn) -> list[dict]:
    cur = conn.execute("""SELECT q.job_id, q.position, q.state, q.reason, q.added_at, q.started_at,
                                 q.finished_at, j.title, j.company, j.job_url, j.source
                          FROM apply_queue q LEFT JOIN jobs j ON j.id = q.job_id
                          ORDER BY q.position""")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
