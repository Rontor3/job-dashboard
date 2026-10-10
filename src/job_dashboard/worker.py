"""The ``worker`` process: the background work the api used to run on its own threads.

    PYTHONPATH=src uv run python -m job_dashboard.worker

It drains the apply queue (started and paused from the api through jobs.db, see apply/queue_control.py), watches
parked forms for a hand submit, runs the daily Gmail scan, and runs Refresh and the hiring-post refresh when the api
asks (worker_jobs.py). Those two are the only users of the embedding model, so it lives here, loaded on first use. The api stays stateless: it only reads and writes
jobs.db. Only one career_agent run happens at a time across both processes (AgentRunState's lock file).
"""
from __future__ import annotations

import threading
import time

from job_dashboard import paths, worker_jobs
from job_dashboard.apply import queue_control
from job_dashboard.db import init_db


def run(db_path, runner, ticks: int | None = None, clock=time.time, sleep=time.sleep, every_s: float = 1.0,
        jobs: dict | None = None) -> None:
    """Hand queue requests to ``runner`` and job requests to ``jobs`` ({name: (start, snapshot)}) and report
    their status, ``ticks`` times (forever when None)."""
    n = 0
    while ticks is None or n < ticks:
        try:
            conn = init_db(db_path)
            try:
                queue_control.sync(conn, runner, clock)
                for name, (start, snapshot) in (jobs or {}).items():
                    worker_jobs.sync(conn, name, start, snapshot, clock)
            finally:
                conn.close()
        except Exception as e:                       # DB busy...: try again next tick
            print(f"[worker] sync skipped ({type(e).__name__}: {e})", flush=True)
        n += 1
        if ticks is None or n < ticks:
            sleep(every_s)


def main() -> None:
    from job_dashboard.env import load_app_env
    load_app_env()

    from job_dashboard.api.agent_routes import AgentRunState
    from job_dashboard.api.mail_routes import MailScanner
    from job_dashboard.api.queue_routes import make_agent_launch
    from job_dashboard.apply.queue_runner import QueueRunner
    from job_dashboard.apply.submit_watch import SubmitWatcher

    db = str(paths.DB)
    watcher = SubmitWatcher(db)
    watcher.start()
    threading.Thread(target=MailScanner(db).loop, name="mail-scan-daily", daemon=True).start()
    runner = QueueRunner(db, make_agent_launch(AgentRunState()), watcher=watcher)
    print("[worker] up: apply queue, submit watcher, daily mail scan, Refresh, hiring refresh", flush=True)
    run(db, runner, jobs=background_jobs(db))


def background_jobs(db) -> dict:
    """Refresh and the hiring-post refresh, each as (start, snapshot) for ``run``."""
    from job_dashboard.api.refresh_job import RefreshState, default_pipeline_runner
    from job_dashboard.linkedin.hiring_job import make_runner
    from job_dashboard.linkedin.hiring_refresh import HiringRefresh, RefreshBusy
    from job_dashboard.match.embedder import LazyModel

    model = LazyModel()                              # one copy, loaded by whichever job needs it first
    refresh = RefreshState()
    hiring, hiring_run = HiringRefresh(), make_runner(db, model=model)

    def start_hiring():
        try:
            hiring.start(hiring_run)
        except RefreshBusy:
            pass

    return {
        "refresh": (lambda: refresh.start(lambda on_stage: default_pipeline_runner(db, on_stage, model)),
                    refresh.snapshot),
        "hiring": (start_hiring, hiring.status),
    }


if __name__ == "__main__":
    main()
