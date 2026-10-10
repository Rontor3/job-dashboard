"""The Inbox's updates: what happened while the user wasn't looking, one row per event, newest first.

Producers write here as things happen (the apply queue when a run ends, the submit watcher when a parked form goes
out, the mail scan when an email moves a tracker card, Refresh when it finds strong matches, the in-app agent when it
wants the user's attention). The Inbox shows them under the questions that block applications, and every card can
be handed to the agent. ``dedupe`` keeps one live row per key: a newer event about the same thing replaces it.

    kind       submitted | parked | failed | matches | tracker | agent
    level      info | success | action (needs the user) | warning
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

KINDS = ("submitted", "parked", "failed", "matches", "tracker", "agent")
LEVELS = ("info", "success", "action", "warning")
_COLS = ("id", "at", "kind", "level", "title", "body", "job_id", "data", "source", "read_at", "dismissed_at")


def ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS notification (
        id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL, level TEXT NOT NULL,
        title TEXT NOT NULL, body TEXT, job_id INTEGER, data TEXT, source TEXT, dedupe TEXT,
        read_at TEXT, dismissed_at TEXT)""")
    conn.execute("CREATE INDEX IF NOT EXISTS notification_live ON notification (dismissed_at, id)")
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(r) -> dict:
    d = dict(zip(_COLS, r))
    d["data"] = json.loads(d["data"]) if d["data"] else {}
    return d


def notify(conn, kind: str, title: str, body: str | None = None, *, level: str = "info", job_id: int | None = None,
           data: dict | None = None, source: str = "app", dedupe: str | None = None) -> int:
    """Record one event; returns its id. Never raises on a bad kind/level from a producer: it falls back."""
    ensure(conn)
    kind = kind if kind in KINDS else "agent"
    level = level if level in LEVELS else "info"
    if dedupe:
        conn.execute("UPDATE notification SET dismissed_at=? WHERE dedupe=? AND dismissed_at IS NULL", (_now(), dedupe))
    cur = conn.execute(
        "INSERT INTO notification (at, kind, level, title, body, job_id, data, source, dedupe) VALUES (?,?,?,?,?,?,?,?,?)",
        (_now(), kind, level, title[:200], (body or None) and body[:2000], job_id,
         json.dumps(data) if data else None, source, dedupe))
    conn.commit()
    return cur.lastrowid


def safe_notify(conn, *args, **kwargs) -> None:
    """For producers whose own work must never fail because the Inbox couldn't be written."""
    try:
        notify(conn, *args, **kwargs)
    except Exception as e:                                  # noqa: BLE001
        print(f"[notify] skipped ({type(e).__name__}: {e})", flush=True)


def listing(conn, limit: int = 50, unread_only: bool = False) -> list[dict]:
    ensure(conn)
    where = "dismissed_at IS NULL" + (" AND read_at IS NULL" if unread_only else "")
    rows = conn.execute(f"SELECT {', '.join(_COLS)} FROM notification WHERE {where} ORDER BY id DESC LIMIT ?",
                        (max(1, min(limit, 200)),)).fetchall()
    return [_row(r) for r in rows]


def unread(conn) -> int:
    ensure(conn)
    return conn.execute("SELECT COUNT(*) FROM notification WHERE dismissed_at IS NULL AND read_at IS NULL").fetchone()[0]


def mark_read(conn, ids: list[int] | None = None) -> int:
    """Mark these (or, with None, all) as read; returns how many changed."""
    ensure(conn)
    if ids is None:
        cur = conn.execute("UPDATE notification SET read_at=? WHERE read_at IS NULL", (_now(),))
    else:
        marks = ",".join("?" * len(ids)) or "NULL"
        cur = conn.execute(f"UPDATE notification SET read_at=? WHERE read_at IS NULL AND id IN ({marks})", (_now(), *ids))
    conn.commit()
    return cur.rowcount


def dismiss(conn, notif_id: int) -> bool:
    ensure(conn)
    cur = conn.execute("UPDATE notification SET dismissed_at=?, read_at=COALESCE(read_at, ?) WHERE id=? "
                       "AND dismissed_at IS NULL", (_now(), _now(), notif_id))
    conn.commit()
    return cur.rowcount == 1
