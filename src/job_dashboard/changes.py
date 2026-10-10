"""The change log: every write to the user's data, from the in-app agent or the UI, kept forever, with Undo.

Who made a change comes from the request (``Actor``): the agent service sends ``X-Agent-Session`` and
``X-Agent-Message`` on every call, anything else is the UI. ``apply`` writes one field through its entity's
writer and logs ``before`` and ``after``; ``undo`` writes ``before`` back the same way, and is itself logged.
Writes that are not field edits (a review click, a scan) are logged as actions, which can't be undone.
Values are stored as JSON. Secret values are never passed in here: their rows say only "set".
"""
from __future__ import annotations

import contextvars
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass
class Actor:
    kind: str = "ui"                         # "agent" | "ui"
    session_id: str | None = None
    message_id: str | None = None
    changes: list[dict] = field(default_factory=list)      # rows logged while serving this request
    logged: bool = False                                    # the route went through the log, even if nothing changed


_actor: contextvars.ContextVar[Actor | None] = contextvars.ContextVar("change_actor", default=None)


def current() -> Actor:
    return _actor.get() or Actor()


def bind(actor: Actor):
    return _actor.set(actor)


def unbind(token) -> None:
    _actor.reset(token)


@dataclass(frozen=True)
class Entity:
    read: Callable[[Any, str, str], Any]               # (conn, entity_id, field) -> value
    write: Callable[[Any, str, str, Any], None]        # (conn, entity_id, field, value)


ENTITIES: dict[str, Entity] = {}


def register(name: str, read, write) -> None:
    ENTITIES[name] = Entity(read, write)


def ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS change_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL,
        session_id TEXT, message_id TEXT, entity TEXT NOT NULL, entity_id TEXT, field TEXT,
        before TEXT, after TEXT, undoable INTEGER NOT NULL DEFAULT 1, undone_at TEXT, undo_of INTEGER)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_change_log_session ON change_log(session_id, id)")
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _summary(row_id: int, entity: str, entity_id, fld, before, after, undoable: bool) -> dict:
    clip = lambda v: v[:200] + "…" if isinstance(v, str) and len(v) > 200 else v    # noqa: E731
    return {"id": row_id, "entity": entity, "entity_id": entity_id, "field": fld,
            "before": clip(before), "after": clip(after), "undoable": undoable}


def record(conn, entity: str, entity_id, fld: str | None, before=None, after=None, *, undoable: bool = True) -> int | None:
    """Log one change by the current actor. An edit that changes nothing is not logged (None)."""
    a = current()
    a.logged = True
    if undoable and before == after:
        return None
    ensure(conn)
    cur = conn.execute(
        "INSERT INTO change_log (at, actor, session_id, message_id, entity, entity_id, field, before, after, undoable) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (_now(), a.kind, a.session_id, a.message_id, entity, None if entity_id is None else str(entity_id), fld,
         json.dumps(before), json.dumps(after), int(undoable)))
    conn.commit()
    a.changes.append(_summary(cur.lastrowid, entity, entity_id, fld, before, after, undoable))
    return cur.lastrowid


def apply(conn, entity: str, entity_id, fld: str, value) -> int | None:
    """Write ``value`` through the entity's writer and log it. KeyError for an unknown entity."""
    e = ENTITIES[entity]
    before = e.read(conn, str(entity_id), fld)
    e.write(conn, str(entity_id), fld, value)
    return record(conn, entity, entity_id, fld, before, value)


class CannotUndo(Exception):
    pass


def undo(conn, change_id: int) -> int | None:
    """Write the change's ``before`` back; returns the new (undo) row's id. KeyError if there is no such change,
    CannotUndo for an action or a change already undone."""
    ensure(conn)
    row = conn.execute("SELECT entity, entity_id, field, before, undoable, undone_at FROM change_log WHERE id=?",
                       (change_id,)).fetchone()
    if row is None:
        raise KeyError(change_id)
    entity, entity_id, fld, before, undoable, undone_at = row
    if not undoable or entity not in ENTITIES:
        raise CannotUndo("this change can't be undone")
    if undone_at:
        raise CannotUndo("already undone")
    new_id = apply(conn, entity, entity_id, fld, json.loads(before))
    conn.execute("UPDATE change_log SET undone_at=? WHERE id=?", (_now(), change_id))
    if new_id is not None:
        conn.execute("UPDATE change_log SET undo_of=? WHERE id=?", (change_id, new_id))
    conn.commit()
    return new_id


def listing(conn, session_id: str | None = None, limit: int = 100, before_id: int | None = None) -> list[dict]:
    ensure(conn)
    where, args = [], []
    if session_id:
        where.append("session_id = ?")
        args.append(session_id)
    if before_id:
        where.append("id < ?")
        args.append(before_id)
    sql = ("SELECT id, at, actor, session_id, message_id, entity, entity_id, field, before, after, undoable, "
           "undone_at, undo_of FROM change_log" + (" WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY id DESC LIMIT ?")
    cols = ("id", "at", "actor", "session_id", "message_id", "entity", "entity_id", "field", "before", "after",
            "undoable", "undone_at", "undo_of")
    out = []
    for r in conn.execute(sql, (*args, max(1, min(limit, 500)))):
        d = dict(zip(cols, r))
        d["before"], d["after"] = json.loads(d["before"]), json.loads(d["after"])
        d["undoable"] = bool(d["undoable"])
        out.append(d)
    return out
