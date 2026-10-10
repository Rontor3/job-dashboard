import sys

from fastapi.testclient import TestClient

from job_dashboard import worker
from job_dashboard.api.agent_routes import AgentRunState
from job_dashboard.api.app import create_app
from job_dashboard.apply.queue_control import STALE_S, QueueControl
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing


class FakeRunner:
    def __init__(self):
        self.calls, self.running, self.paused, self.job_id = [], False, False, None

    def start(self):
        self.calls.append("start")
        self.running, self.paused = True, False

    def pause(self):
        self.calls.append("pause")
        self.paused = True

    def status(self):
        return {"running": self.running, "paused": self.paused, "job_id": self.job_id if self.running else None}


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def _db(tmp_path):
    db = str(tmp_path / "jobs.db")
    c = init_db(db)
    insert_job(c, JobListing(source="s", title="Job", company="Acme", job_url="https://x/1", description="jd"))
    c.close()
    return db


def test_start_and_pause_reach_the_worker_and_its_status_comes_back(tmp_path):
    db, runner, clock = _db(tmp_path), FakeRunner(), Clock()
    control = QueueControl(db, clock=clock)
    assert control.status() == {"running": False, "paused": False, "job_id": None, "worker": False}

    control.start()
    worker.run(db, runner, ticks=1, clock=clock, sleep=lambda s: None)
    runner.job_id = 7
    worker.run(db, runner, ticks=1, clock=clock, sleep=lambda s: None)
    assert runner.calls == ["start"]
    assert control.status() == {"running": True, "paused": False, "job_id": 7, "worker": True}

    control.pause()
    assert control.status()["paused"] is True                # shown at once, before the worker acts
    worker.run(db, runner, ticks=1, clock=clock, sleep=lambda s: None)
    assert runner.calls == ["start", "pause"]


def test_a_silent_worker_reads_as_not_running(tmp_path):
    db, runner, clock = _db(tmp_path), FakeRunner(), Clock()
    control = QueueControl(db, clock=clock)
    runner.running, runner.job_id = True, 3
    worker.run(db, runner, ticks=1, clock=clock, sleep=lambda s: None)
    clock.t += STALE_S + 1
    assert control.status() == {"running": False, "paused": False, "job_id": None, "worker": False}


def test_the_api_queue_hands_start_to_the_worker_instead_of_running_jobs_itself(tmp_path):
    db = _db(tmp_path)
    c = TestClient(create_app(db_path=db))
    job_id = init_db(db).execute("SELECT id FROM jobs").fetchone()[0]
    body = c.post("/api/queue", json={"job_id": job_id, "start": True}).json()
    assert body["running"] is False and body["worker"] is False
    assert init_db(db).execute("SELECT request FROM queue_control").fetchone()[0] == "start"
    assert c.app.state.submit_watcher is None                # the worker watches parked forms, not the api


def test_apply_agent_status_shows_a_run_the_worker_is_doing(tmp_path):
    db, runner = _db(tmp_path), FakeRunner()
    runner.running, runner.job_id = True, 5
    worker.run(db, runner, ticks=1, sleep=lambda s: None)
    c = TestClient(create_app(db_path=db))
    body = c.get("/api/apply-agent/status").json()
    assert body["running"] is True and body["job_id"] == 5


def test_one_agent_run_at_a_time_across_processes(tmp_path):
    api, wk = AgentRunState(), AgentRunState()               # one in the api, one in the worker
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    assert api.start(1, cmd, str(tmp_path), {}, tmp_path / "1.log")
    try:
        assert wk.start(2, cmd, str(tmp_path), {}, tmp_path / "2.log") is False
    finally:
        api.stop()
    assert wk.start(2, [sys.executable, "-c", "pass"], str(tmp_path), {}, tmp_path / "2.log")
    assert wk.wait() == 0
