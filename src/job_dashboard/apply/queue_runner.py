"""Drains the apply queue one job at a time on a daemon thread.

Per job: build the career_agent argv (always --park so nothing waits on the
human; --submit --autonomous only where the board's standing authorization
`autosubmit_<board>` is on, else --review), hand it to `launch`, read the
--result-json it wrote, and record the verdict (queue.py + jobs.status).
`launch(job_id, argv, result_path) -> exit_code` is injected; the API wires it
to AgentRunState so the one-Chrome single-flight lock still holds.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading

from job_dashboard import qa_store
from job_dashboard.apply import queue as q
from job_dashboard.apply.outcome import outcome
from job_dashboard.db import VALID_STATUSES, init_db, set_job_status

def autosubmit_key(url: str) -> str:
    from career_agent.boards.profiles import board_for
    board = board_for(url or "")
    name = board["id"].split(":", 1)[1] if board else "career_site"
    return f"autosubmit_{name}"


def job_target(job: dict) -> str | None:
    """Same choice as the Apply button: an external apply link beats the listing."""
    if job.get("apply_kind") == "external" and job.get("apply_url"):
        return job["apply_url"]
    return job.get("job_url")


def _job(conn, job_id: int) -> dict | None:
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT id, job_url, apply_kind, apply_url FROM jobs WHERE id = ?",
                           (job_id,)).fetchone()
    finally:
        conn.row_factory = None
    return dict(row) if row else None


class QueueRunner:
    def __init__(self, db_path: str, launch, result_dir: str | None = None):
        self.db_path, self.launch = db_path, launch
        self.result_dir = result_dir or tempfile.gettempdir()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._paused = False
        self._job_id: int | None = None

    # -- control --------------------------------------------------------
    def start(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                self._paused = False
                return False
            self._paused = False
            self._thread = threading.Thread(target=self.drain, name="apply-queue", daemon=True)
            self._thread.start()
            return True

    def pause(self) -> None:
        self._paused = True

    def status(self) -> dict:
        running = self._thread is not None and self._thread.is_alive()
        return {"running": running, "paused": self._paused, "job_id": self._job_id if running else None}

    # -- work -----------------------------------------------------------
    def drain(self) -> None:
        """Run queued jobs until none are left or the queue is paused."""
        conn = init_db(self.db_path)
        try:
            while not self._paused:
                job_id = q.next_queued(conn)
                if job_id is None:
                    break
                self._job_id = job_id
                try:
                    self._run_one(conn, job_id)
                finally:
                    self._job_id = None
        finally:
            conn.close()

    def argv(self, conn, url: str, job_id: int, result_path: str) -> list[str]:
        argv = [sys.executable, "-m", "career_agent.apply", "--job-id", str(job_id), "--url", url,
                "--park", "--result-json", result_path]
        try:
            authorized = qa_store.get_setting(conn, autosubmit_key(url)) == "1"
        except KeyError:
            authorized = False
        wait = qa_store.get_setting(conn, "telegram_wait_minutes")
        if wait.isdigit() and int(wait) > 0:
            argv += ["--ask-wait-minutes", wait]
        return argv + (["--submit", "--autonomous"] if authorized else ["--review"])

    def _run_one(self, conn, job_id: int) -> None:
        job = _job(conn, job_id)
        url = job_target(job) if job else None
        if not url:
            q.mark(conn, job_id, "failed", "job_missing")
            return
        q.mark(conn, job_id, "running")
        result_path = os.path.join(self.result_dir, f"apply_result_{job_id}.json")
        if os.path.exists(result_path):
            os.remove(result_path)
        try:
            code = self.launch(job_id, self.argv(conn, url, job_id, result_path), result_path)
        except Exception as e:
            print(f"[queue] launch failed for job {job_id}: {type(e).__name__}: {e}", flush=True)
            q.mark(conn, job_id, "failed", "launch_error")
            return
        result = None
        try:
            with open(result_path) as fh:
                result = json.load(fh)
        except (OSError, ValueError):
            pass
        state, reason, status = outcome(result, code)
        q.mark(conn, job_id, state, reason)
        if status in VALID_STATUSES:
            set_job_status(conn, job_id, status)
