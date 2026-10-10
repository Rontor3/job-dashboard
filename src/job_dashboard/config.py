"""Non-secret settings, in the ``config`` table of jobs.db, read live by every process.

A value in the table wins; otherwise the environment (``.env``) still counts, so an existing setup keeps working.
``migrate_from_env`` copies the ``.env`` file's values (not the shell's) into the table once, at process start.
Secrets (API keys, tokens) never go here; they stay in ``.env``.

Each key says whether a change takes effect at once (``restart`` None: read on every use, e.g. the LLM client) or
only after the named process restarts. Nothing restarts on its own; the API returns ``restart`` so the UI can say so.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from job_dashboard import paths

DB_PATH = str(paths.DB)


def _number(v: str) -> bool:
    try:
        return float(v) > 0
    except ValueError:
        return False


@dataclass(frozen=True)
class Key:
    help: str
    restart: str | None = None
    valid: Callable[[str], bool] = lambda v: True


KEYS: dict[str, Key] = {
    "LLM_BASE_URL": Key("OpenAI-compatible endpoint (POST {base}/responses)", valid=lambda v: v.startswith("http")),
    "LLM_MODEL": Key("model name sent to the endpoint"),
    "LLM_TIMEOUT": Key("seconds per LLM call", valid=_number),
    "LLM_REASONING_EFFORT": Key("none|low|medium|high", valid=lambda v: v in ("none", "low", "medium", "high")),
    "LLM_NO_TEMPERATURE": Key("1 = never send temperature", valid=lambda v: v in ("0", "1")),
    "AGENT_CDP_PORT": Key("debug port of the agent Chrome", restart="browser", valid=str.isdigit),
    "AGENT_CHROME_PATH": Key("Chrome binary for the agent browser", restart="browser"),
}


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT)")
    return conn


def _stored() -> dict[str, str]:
    conn = _conn()
    try:
        return dict(conn.execute("SELECT key, value FROM config"))
    finally:
        conn.close()


def snapshot() -> dict[str, str | None]:
    """Every key's current value (table, else environment, else None), from one read."""
    stored = _stored()
    return {k: stored.get(k) or os.getenv(k) or None for k in KEYS}


def get(key: str) -> str | None:
    """The table's value, else the environment's, else None."""
    return _stored().get(key) or os.getenv(key) or None


def put(key: str, value: str) -> None:
    """Store ``value`` for a known key; an empty value removes the row (back to the environment/default).
    KeyError for an unknown key, ValueError for an invalid value."""
    spec = KEYS[key]
    value = (value or "").strip()
    if value and not spec.valid(value):
        raise ValueError(f"invalid value for {key}: {spec.help}")
    conn = _conn()
    try:
        if value:
            conn.execute("INSERT INTO config (key, value, updated_at) VALUES (?, ?, datetime('now')) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                         (key, value))
        else:
            conn.execute("DELETE FROM config WHERE key = ?", (key,))
        conn.commit()
    finally:
        conn.close()


def listing() -> list[dict]:
    stored = _stored()
    return [{"key": k, "value": stored.get(k) or os.getenv(k) or None,
             "source": "config" if k in stored else ("env" if os.getenv(k) else None),
             "help": spec.help, "restart": spec.restart} for k, spec in KEYS.items()]


def migrate_from_env(env_path=None) -> list[str]:
    """Copy each key set in the ``.env`` file but not yet in the table. Returns the keys copied."""
    from job_dashboard.env import read_env_file
    values = read_env_file(env_path or paths.REPO_ROOT / ".env")
    stored, moved = _stored(), []
    for k, spec in KEYS.items():
        v = values.get(k)
        if k not in stored and v and spec.valid(v):
            put(k, v)
            moved.append(k)
    return moved
