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
from datetime import datetime, timezone

from job_dashboard import qa_store
from job_dashboard.apply import queue as q
from job_dashboard.apply.outcome import outcome
from job_dashboard.apply.submit_watch import watchable
from job_dashboard.db import VALID_STATUSES, init_db, set_job_status

# parked reasons that mean "a filled form was left open waiting for you": only those can be submitted by hand
LEFT_FOR_REVIEW = {"review", "reached_submit_dry_run", "needs_approval", "submit_unconfirmed", "one_click_needs_autosubmit"}

# run_log lives in jobs.db and is written only by the career_agent child
# (career_agent/apply.py _write_run_log). This is that CREATE TABLE statement
# copied byte for byte — whichever process runs first creates the table, and
# two definitions of one table would only ever be a bug.
_RUN_LOG_TABLE = """
            CREATE TABLE IF NOT EXISTS run_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT,
                url         TEXT,
                job_id      INTEGER,
                stopped_reason TEXT,
                filled      INTEGER,
                escalated   INTEGER,
                submitted   INTEGER,
                result_json TEXT
            )
        """


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


def _run_log_marker(conn) -> int:
    """MAX(run_log.id) before the child is launched, on this same jobs.db the
    child writes its run_log rows to. After the run, a row with a higher id for
    the job must have come from the child itself. run_log exists only once an
    agent has run against this DB, so create it first — the exact statement
    career_agent/apply.py uses. Best effort: the queue must survive a DB that
    refuses the table (the backfill will fail loudly on the same table anyway)."""
    try:
        conn.execute(_RUN_LOG_TABLE)
        conn.commit()
        return conn.execute("SELECT MAX(id) FROM run_log").fetchone()[0] or 0
    except sqlite3.Error as e:
        print(f"[run_log] marker skipped ({e})", flush=True)
        return 0


def _backfill_run_log(conn, job_id: int, url: str | None, reason: str,
                      exit_code: int, result: dict | None, marker: int) -> None:
    """Write the audit row the child never wrote. A child that dies hard — an
    EPIPE crash, a SIGKILL, the stall-kill exit 124, a Claude-limit stop —
    leaves no run_log row, so run history and the submit watcher's run_log
    discovery never learn this run happened. The marker is the source of truth
    either way: even a done/applied run that recorded nothing is backfilled so
    the claimed submit is auditable. The queue is single-flight, so the only
    way the predicate finds a row is a concurrently started CLI run of the SAME
    job landing its own row between marker and check — then the child did
    record and skipping the backfill is the right answer."""
    try:
        if conn.execute("SELECT 1 FROM run_log WHERE job_id=? AND id>?", (job_id, marker)).fetchone():
            return
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()   # naive UTC isoformat, like every run_log ts
        payload = {"backfill": True, "exit_code": exit_code, "result": result,
                   "note": "child died before recording its run — row backfilled by the queue runner"}
        conn.execute(
            "INSERT INTO run_log(ts, url, job_id, stopped_reason, filled, escalated, submitted, result_json)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (now, url, job_id, reason, 0, 0, 0, json.dumps(payload)))
        conn.commit()
        print(f"[run_log] job {job_id}: nothing above marker {marker} — backfilled one "
              f"({reason}, exit {exit_code})", flush=True)
    except sqlite3.Error as e:
        print(f"[run_log] backfill failed ({type(e).__name__}: {e})", flush=True)


class QueueRunner:
    def __init__(self, db_path: str, launch, result_dir: str | None = None, watcher=None):
        self.db_path, self.launch = db_path, launch
        self.watcher = watcher                     # SubmitWatcher: told where a parked form was left open
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
    @staticmethod
    def _promote_trails() -> None:
        """Fold finished runs' reach trails into the ATS graph so the next job benefits."""
        try:
            from career_agent.memory.ats_promote import promote
            promote()
        except Exception as e:                      # learning must never break the queue
            print(f"[queue] ats-graph promote skipped: {type(e).__name__}: {e}", flush=True)

    def drain(self) -> None:
        """Run queued jobs until none are left or the queue is paused."""
        conn = init_db(self.db_path)
        self._promote_trails()                      # runs finished outside the queue (CLI, manual)
        # a 'running' row at drain start belongs to a run the server restart orphaned: back to the queue, not stuck
        conn.execute("UPDATE apply_queue SET state='queued', started_at=NULL WHERE state='running'")
        conn.commit()
        from . import local_model
        started_model = local_model.ensure_running()
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
                    self._promote_trails()
        finally:
            conn.close()
            if started_model:
                local_model.stop()

    def run_one_detached(self, job_id: int, url: str | None = None) -> bool:
        """Run one job on its own thread — the SubmitWatcher's relauncher for a job whose block the human
        cleared on its tab. False when the queue is already draining: then its row is picked up there."""
        if self._thread is not None and self._thread.is_alive():
            return False
        threading.Thread(target=self._run_detached, args=(job_id, url), name=f"apply-watch-{job_id}", daemon=True).start()
        return True

    def _run_detached(self, job_id: int, url: str | None) -> None:
        conn = init_db(self.db_path)
        try:
            self._job_id = job_id
            try:
                self._run_one(conn, job_id, url)
            finally:
                self._promote_trails()
        finally:
            self._job_id = None
            conn.close()

    def argv(self, conn, url: str, job_id: int, result_path: str) -> list[str]:
        argv = [sys.executable, "-m", "career_agent.apply", "--job-id", str(job_id), "--url", url,
                "--park", "--result-json", result_path, "--claude-assist", "--longform"]   # capped at 5 Claude calls per run
        wait = qa_store.get_setting(conn, "telegram_wait_minutes")
        if wait.isdigit() and int(wait) > 0:
            argv += ["--ask-wait-minutes", wait]
        # Whether the form goes out without you is decided at its last step, from the destination site's switch and the
        # answers' approvals (autonomy.autosubmit_policy); otherwise it is left open for your review.
        return argv + ["--review", "--autosubmit-policy"]

    def _run_one(self, conn, job_id: int, target: str | None = None) -> None:
        job = _job(conn, job_id)
        url = target or (job_target(job) if job else None)
        if not url:
            q.mark(conn, job_id, "failed", "job_missing")
            return
        q.mark(conn, job_id, "running")
        marker = _run_log_marker(conn)                 # the child's own rows land above this; anything fewer is a silent death
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
        _backfill_run_log(conn, job_id, url, reason, code, result, marker)
        if self.watcher and result and result.get("url") and not result.get("submitted"):
            if state == "parked" and reason in LEFT_FOR_REVIEW:
                how = "auto" if reason == "submit_unconfirmed" else "manual"
            elif state in ("parked", "failed") and watchable(reason or ""):
                how = reason            # stopped inside a block: clearing it there (or waiting) is worth a re-run
            else:
                how = None
            if how:
                try:
                    self.watcher.register(conn, job_id, result["url"], result.get("run_key"),
                                          result.get("final_tab_id"), how)
                except Exception as e:
                    print(f"[queue] could not register a submit watch for job {job_id}: {e}", flush=True)
        now = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if status in VALID_STATUSES and not (now and now[0] in ("applied", "interviewing", "offer")):
            set_job_status(conn, job_id, status)       # a re-run never downgrades a job you already applied to
