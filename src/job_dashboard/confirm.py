"""Confirmation for the agent's consequential actions: the human presses Confirm, the agent never can.

The agent proposes an action (method, path, body) and the dashboard shows Confirm / Cancel. Confirm, which
FastAPI refuses from the agent, issues a single-use token bound to that exact request. An agent request to a
consequential route without a matching unused token is refused (api/change_routes.py). Requests from the UI need
no token: the human's own click is the confirmation.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone

# Consequential routes (the spec's list: queue or apply, start the queue, Refresh, mail scan, autonomy, auto-submit
# and rate-limit changes, any delete).
CONSEQUENTIAL = [(m, re.compile(p + r"$")) for m, p in (
    ("POST", r"/api/queue"),
    ("POST", r"/api/queue/start"),
    ("POST", r"/api/refresh"),
    ("POST", r"/api/mail-scan"),
    ("POST", r"/api/jobs/\d+/apply-agent"),
    ("POST", r"/api/hiring/refresh"),
    ("POST", r"/api/applied/reconcile"),
    ("PUT", r"/api/queue/autosubmit"),
    ("PUT", r"/api/queue/settings"),
    ("DELETE", r"/api/.+"),
)]


def is_consequential(method: str, path: str) -> bool:
    path = path.split("?", 1)[0]
    return any(m == method.upper() and p.match(path) for m, p in CONSEQUENTIAL)


def ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS confirmation (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, session_id TEXT,
        method TEXT NOT NULL, path TEXT NOT NULL, body TEXT, summary TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', token TEXT, decided_at TEXT, used_at TEXT)""")
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canon(body) -> str:
    """One spelling per request body: parsed JSON re-dumped with sorted keys, else the raw text."""
    if body in (None, b"", ""):
        return "null"
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return json.dumps(body)
    return json.dumps(body, sort_keys=True)


_COLS = ("id", "created_at", "session_id", "method", "path", "body", "summary", "status", "decided_at", "used_at")


def _row(r) -> dict:
    d = dict(zip(_COLS, r))
    d["body"] = json.loads(d["body"])
    return d


def propose(conn, session_id: str | None, method: str, path: str, body, summary: str) -> dict:
    if not is_consequential(method, path):
        raise ValueError(f"{method} {path} needs no confirmation; call it directly")
    ensure(conn)
    cur = conn.execute("INSERT INTO confirmation (created_at, session_id, method, path, body, summary) "
                       "VALUES (?,?,?,?,?,?)", (_now(), session_id, method.upper(), path, _canon(body), summary))
    conn.commit()
    return get(conn, cur.lastrowid)


def get(conn, conf_id: int) -> dict | None:
    ensure(conn)
    r = conn.execute(f"SELECT {', '.join(_COLS)} FROM confirmation WHERE id=?", (conf_id,)).fetchone()
    return _row(r) if r else None


def listing(conn, session_id: str | None = None, status: str | None = None) -> list[dict]:
    ensure(conn)
    where, args = [], []
    if session_id:
        where.append("session_id=?")
        args.append(session_id)
    if status:
        where.append("status=?")
        args.append(status)
    sql = f"SELECT {', '.join(_COLS)} FROM confirmation" + (" WHERE " + " AND ".join(where) if where else "")
    return [_row(r) for r in conn.execute(sql + " ORDER BY id DESC LIMIT 100", args)]


def decide(conn, conf_id: int, confirmed: bool) -> dict:
    """The human's answer. Returns the record, with the token when confirmed. KeyError / ValueError if it can't."""
    c = get(conn, conf_id)
    if c is None:
        raise KeyError(conf_id)
    if c["status"] != "pending":
        raise ValueError(f"already {c['status']}")
    token = secrets.token_urlsafe(24) if confirmed else None
    conn.execute("UPDATE confirmation SET status=?, token=?, decided_at=? WHERE id=?",
                 ("confirmed" if confirmed else "cancelled", token, _now(), conf_id))
    conn.commit()
    return {**get(conn, conf_id), "token": token}


def consume(conn, token: str | None, method: str, path: str, body) -> bool:
    """True once, for a confirmed token issued for exactly this request."""
    if not token:
        return False
    ensure(conn)
    r = conn.execute("SELECT id, method, path, body FROM confirmation WHERE token=? AND status='confirmed' "
                     "AND used_at IS NULL", (token,)).fetchone()
    if r is None or r[1] != method.upper() or r[2] != path or r[3] != _canon(body):
        return False
    cur = conn.execute("UPDATE confirmation SET used_at=?, status='used' WHERE id=? AND used_at IS NULL",
                       (_now(), r[0]))
    conn.commit()
    return cur.rowcount == 1
