"""The apply queue's hand-off between the ``api`` and ``worker`` processes, through one row in jobs.db.

The api records a request (start / pause); the worker, every second, takes the request, applies it to its
QueueRunner and writes back the runner's status with a heartbeat. ``QueueControl`` has the QueueRunner's
start/pause/status surface, so the queue routes don't care which process runs the queue.
"""
from __future__ import annotations

import sqlite3
import time

STALE_S = 15                    # no heartbeat for this long = the worker isn't running


def ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS queue_control (
        id INTEGER PRIMARY KEY CHECK (id = 1), request TEXT,
        running INTEGER NOT NULL DEFAULT 0, paused INTEGER NOT NULL DEFAULT 0, job_id INTEGER, beat_at REAL)""")
    conn.execute("INSERT OR IGNORE INTO queue_control (id) VALUES (1)")
    conn.commit()


class QueueControl:
    """The api side."""

    def __init__(self, db_path, clock=time.time):
        self.db_path, self.clock = str(db_path), clock
        conn = self._conn()
        try:
            ensure(conn)
        finally:
            conn.close()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10)     # status is polled every second: no init_db, no writes

    def _write(self, sql: str, *args) -> None:
        conn = self._conn()
        try:
            conn.execute(sql, args)
            conn.commit()
        finally:
            conn.close()

    def start(self) -> bool:
        self._write("UPDATE queue_control SET request='start', paused=0 WHERE id=1")
        return True

    def pause(self) -> None:
        self._write("UPDATE queue_control SET request='pause', paused=1 WHERE id=1")

    def status(self) -> dict:
        conn = self._conn()
        try:
            running, paused, job_id, beat = conn.execute(
                "SELECT running, paused, job_id, beat_at FROM queue_control WHERE id=1").fetchone()
        finally:
            conn.close()
        up = beat is not None and self.clock() - beat < STALE_S
        running = bool(up and running)
        return {"running": running, "paused": bool(paused), "job_id": job_id if running else None, "worker": up}


def sync(conn, runner, clock=time.time) -> None:
    """The worker side: apply a pending request to ``runner`` and report its status, in one transaction."""
    ensure(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        request = conn.execute("SELECT request FROM queue_control WHERE id=1").fetchone()[0]
        if request == "start":
            runner.start()
        elif request == "pause":
            runner.pause()
        st = runner.status()
        conn.execute("UPDATE queue_control SET request=NULL, running=?, paused=?, job_id=?, beat_at=? WHERE id=1",
                     (int(st["running"]), int(st["paused"]), st["job_id"], clock()))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
