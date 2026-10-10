"""Long background jobs (Refresh, the hiring-post refresh) run in the ``worker`` process, not the api.

They are the only work that loads the embedding model, scrapes through the agent Chrome or runs for minutes, so
the api stays light: it starts in a second, never holds the model in memory, and a restart of the api doesn't
kill a running Refresh. The hand-off is one row per job in jobs.db, like the apply queue (apply/queue_control.py):
the api writes ``request='start'``; the worker, every tick, starts the job on its own thread and writes back the
job's status with a heartbeat. The status dict is whatever the job's state object reports, so the api's routes
answer with the same shape as when the job ran in-process.
"""
from __future__ import annotations

import json
import sqlite3
import time

STALE_S = 15                    # no heartbeat for this long = the worker isn't running


def ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS worker_job (
        name TEXT PRIMARY KEY, request TEXT, status TEXT, beat_at REAL)""")
    conn.commit()


class RemoteJob:
    """The api side of one job: ``start()`` and ``status()``, like the in-process state objects."""

    def __init__(self, db_path, name: str, idle: dict, clock=time.time):
        self.db_path, self.name, self.idle, self.clock = str(db_path), name, idle, clock
        conn = self._conn()
        try:
            ensure(conn)
            conn.execute("INSERT OR IGNORE INTO worker_job (name) VALUES (?)", (name,))
            conn.commit()
        finally:
            conn.close()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10)

    def status(self) -> dict:
        conn = self._conn()
        try:
            request, status, beat = conn.execute(
                "SELECT request, status, beat_at FROM worker_job WHERE name=?", (self.name,)).fetchone()
        finally:
            conn.close()
        up = beat is not None and self.clock() - beat < STALE_S
        out = {**self.idle, **(json.loads(status) if status else {}), "worker": up}
        if request == "start":                       # asked for; the worker picks it up within a second
            out.update({"running": True, "stage": "queued"} if "running" in self.idle
                       else {"state": "running", "stage": "starting"}, queued=True)
        return out

    def start(self) -> bool:
        """Ask the worker to start the job. False if it is already running or already asked for."""
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            request, status = conn.execute("SELECT request, status FROM worker_job WHERE name=?",
                                           (self.name,)).fetchone()
            busy = request == "start" or _running(json.loads(status) if status else {})
            if not busy:
                conn.execute("UPDATE worker_job SET request='start' WHERE name=?", (self.name,))
            conn.commit()
            return not busy
        finally:
            conn.close()


def _running(status: dict) -> bool:
    return bool(status.get("running")) or status.get("state") == "running"


def sync(conn, name: str, start, snapshot, clock=time.time) -> None:
    """The worker side for one job: start it if asked (``start()``), then report ``snapshot()``."""
    ensure(conn)
    conn.execute("INSERT OR IGNORE INTO worker_job (name) VALUES (?)", (name,))
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        request = conn.execute("SELECT request FROM worker_job WHERE name=?", (name,)).fetchone()[0]
        if request == "start":
            start()
        conn.execute("UPDATE worker_job SET request=NULL, status=?, beat_at=? WHERE name=?",
                     (json.dumps(snapshot(), default=str), clock(), name))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
