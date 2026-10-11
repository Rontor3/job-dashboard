"""Where an agent-driven application stands (spec 2026-10-11-agent-driven-apply-design.md).

`apply_run`: one row per job, the latest agent run. `state` is running | paused | submitted | skipped | failed;
`reason` is the code (captcha, account_needed, needs_answers, review, ...), `detail` the agent's words for the user.
`tab_open` says whether the page the run stopped on is still open in the agent Chrome.
Also the job's priority (`jobs.priority`): low | normal | high | dream."""
from __future__ import annotations

from datetime import datetime, timezone

PRIORITIES = ("low", "normal", "high", "dream")
TERMINAL = {"submitted", "paused", "skipped", "failed"}
STATES = TERMINAL | {"running"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS apply_run (
        job_id INTEGER PRIMARY KEY, run_key TEXT, agent_session TEXT, state TEXT NOT NULL, reason TEXT, detail TEXT,
        url TEXT, tab_target_id TEXT, tab_open INTEGER NOT NULL DEFAULT 0, step INTEGER NOT NULL DEFAULT 0,
        priority TEXT, paused_at TEXT, updated_at TEXT NOT NULL)""")
    if "priority" not in [r[1] for r in conn.execute("PRAGMA table_info(jobs)")]:
        conn.execute("ALTER TABLE jobs ADD COLUMN priority TEXT")
    conn.commit()


def priority(conn, job_id: int) -> str:
    """The job's priority, else the default setting, else normal."""
    ensure(conn)
    r = conn.execute("SELECT priority FROM jobs WHERE id=?", (job_id,)).fetchone()
    if r and r[0] in PRIORITIES:
        return r[0]
    from job_dashboard import qa_store
    d = qa_store.get_setting(conn, "apply_priority_default")
    return d if d in PRIORITIES else "normal"


def set_priority(conn, job_id: int, level: str) -> None:
    if level not in PRIORITIES:
        raise ValueError(f"priority must be one of {', '.join(PRIORITIES)}")
    ensure(conn)
    conn.execute("UPDATE jobs SET priority=? WHERE id=?", (level, job_id))
    conn.commit()


def hold_priorities(conn) -> set[str]:
    from job_dashboard import qa_store
    raw = qa_store.get_setting(conn, "apply_hold_priorities")
    return {p.strip() for p in raw.split(",") if p.strip() in PRIORITIES}


def save(conn, job_id: int, **fields) -> None:
    """Upsert the job's run row with the given columns."""
    ensure(conn)
    if "state" in fields and fields["state"] not in STATES:
        raise ValueError(f"unknown run state {fields['state']!r}")
    fields["updated_at"] = _now()
    if fields.get("state") == "paused":
        fields.setdefault("paused_at", fields["updated_at"])
    cols = list(fields)
    conn.execute(
        f"INSERT INTO apply_run (job_id, state, {', '.join(c for c in cols if c != 'state')}) "
        f"VALUES (?, ?, {', '.join('?' for c in cols if c != 'state')}) "
        f"ON CONFLICT(job_id) DO UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in cols)}",
        [job_id, fields.get("state", "running"), *[fields[c] for c in cols if c != "state"]])
    conn.commit()


def get(conn, job_id: int) -> dict | None:
    ensure(conn)
    cur = conn.execute("SELECT * FROM apply_run WHERE job_id=?", (job_id,))
    r = cur.fetchone()
    return dict(zip([c[0] for c in cur.description], r)) if r else None


def open_paused(conn) -> list[dict]:
    """Paused runs whose tab is still open, oldest first."""
    ensure(conn)
    cur = conn.execute("SELECT * FROM apply_run WHERE state='paused' AND tab_open=1 ORDER BY paused_at")
    return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
