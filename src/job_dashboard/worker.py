"""The ``worker`` process: the background work the api used to run on its own threads.

    PYTHONPATH=src uv run python -m job_dashboard.worker

It drains the apply queue (started and paused from the api through jobs.db, see apply/queue_control.py), watches
parked forms for a hand submit, and runs the daily Gmail scan. The api stays stateless: it only reads and writes
jobs.db. Only one career_agent run happens at a time across both processes (AgentRunState's lock file).
"""
from __future__ import annotations

import threading
import time

from job_dashboard import paths
from job_dashboard.apply import queue_control
from job_dashboard.db import init_db


def run(db_path, runner, ticks: int | None = None, clock=time.time, sleep=time.sleep, every_s: float = 1.0) -> None:
    """Hand queue requests to ``runner`` and report its status, ``ticks`` times (forever when None)."""
    n = 0
    while ticks is None or n < ticks:
        try:
            conn = init_db(db_path)
            try:
                queue_control.sync(conn, runner, clock)
            finally:
                conn.close()
        except Exception as e:                       # DB busy...: try again next tick
            print(f"[worker] queue sync skipped ({type(e).__name__}: {e})", flush=True)
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
    print("[worker] up: apply queue, submit watcher, daily mail scan", flush=True)
    run(db, runner)


if __name__ == "__main__":
    main()
