"""Refresh and the hiring refresh run in the worker; the api only asks and reports (job_dashboard/worker_jobs.py)."""
import threading

from fastapi.testclient import TestClient

from job_dashboard import worker_jobs
from job_dashboard.api.app import create_app
from job_dashboard.api.refresh_job import RefreshState
from job_dashboard.db import init_db
from job_dashboard.match.embedder import LazyModel


def _db(tmp_path):
    path = str(tmp_path / "t.db")
    init_db(path).close()
    return path


def _sync(db, name, start, snapshot, now=1000.0):
    conn = init_db(db)
    try:
        worker_jobs.sync(conn, name, start, snapshot, clock=lambda: now)
    finally:
        conn.close()


def test_the_api_asks_and_the_worker_runs_and_reports(tmp_path):
    db = _db(tmp_path)
    job = worker_jobs.RemoteJob(db, "refresh", idle=RefreshState().snapshot(), clock=lambda: 1001.0)
    assert job.status() == {**RefreshState().snapshot(), "worker": False}
    assert job.start() is True
    assert job.start() is False                                  # already asked for
    assert job.status()["queued"] is True

    state, release = RefreshState(), threading.Event()
    started = []
    _sync(db, "refresh", lambda: started.append(state.start(lambda on_stage: release.wait(5) and {})), state.snapshot)
    assert started == [True]
    body = job.status()
    assert body["running"] is True and body["worker"] is True and "queued" not in body
    assert job.start() is False                                  # running
    release.set()


def test_a_silent_worker_shows_as_down(tmp_path):
    db = _db(tmp_path)
    _sync(db, "hiring", lambda: None, lambda: {"state": "idle"}, now=1000.0)
    assert worker_jobs.RemoteJob(db, "hiring", idle={}, clock=lambda: 1100.0).status()["worker"] is False


def test_in_worker_routes_never_run_the_job_in_the_api(tmp_path):
    db = _db(tmp_path)
    c = TestClient(create_app(db_path=db, in_worker=True))
    assert c.post("/api/refresh").json() == {"started": True}
    assert c.post("/api/refresh").status_code == 409
    assert c.get("/api/refresh/status").json()["queued"] is True
    body = c.post("/api/hiring/refresh").json()                  # even without background=true: no blocking
    assert body["started"] is True and body["state"] == "running"
    assert c.get("/api/hiring/refresh/status").json()["queued"] is True


def test_the_embedding_model_loads_on_first_use_only_once():
    loads = []

    class Fake:
        def encode(self, texts):
            return texts

    m = LazyModel(loader=lambda: loads.append(1) or Fake())
    assert loads == []
    assert m.encode(["a"]) == ["a"] and m.encode(["b"]) == ["b"]
    assert loads == [1]
