import threading
import time

import pytest
from fastapi.testclient import TestClient

from job_dashboard.api.app import create_app
from job_dashboard.db import init_db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "t.db"
    init_db(path).close()
    return str(path)


def test_refresh_runs_fake_pipeline_and_reports_result(db_path):
    def fake_runner(path, on_stage):
        on_stage("ingesting")
        on_stage("scoring")
        return {"ingest": {"new_jobs": 3}, "embed_scored": 3, "embed_skipped": None}

    tc = TestClient(create_app(db_path=db_path, pipeline_runner=fake_runner))
    assert tc.post("/api/refresh").json() == {"started": True}

    deadline = time.time() + 5
    while time.time() < deadline:
        body = tc.get("/api/refresh/status").json()
        if not body["running"] and body["stage"] == "done":
            break
        time.sleep(0.02)
    assert body["stage"] == "done"
    assert body["last_result"]["ingest"]["new_jobs"] == 3
    assert body["error"] is None


def test_refresh_409_while_running(db_path):
    release = threading.Event()

    def slow_runner(path, on_stage):
        release.wait(timeout=5)
        return {"ingest": {"new_jobs": 0}, "embed_scored": 0, "embed_skipped": None}

    tc = TestClient(create_app(db_path=db_path, pipeline_runner=slow_runner))
    assert tc.post("/api/refresh").status_code == 200
    assert tc.post("/api/refresh").status_code == 409
    release.set()
    deadline = time.time() + 5
    while time.time() < deadline and tc.get("/api/refresh/status").json()["running"]:
        time.sleep(0.02)
    assert tc.post("/api/refresh").status_code == 200  # can run again after finish
    deadline = time.time() + 5
    while time.time() < deadline and tc.get("/api/refresh/status").json()["running"]:
        time.sleep(0.02)


def test_refresh_error_surfaces_in_status(db_path):
    def broken_runner(path, on_stage):
        raise RuntimeError("source exploded")

    tc = TestClient(create_app(db_path=db_path, pipeline_runner=broken_runner))
    tc.post("/api/refresh")
    deadline = time.time() + 5
    while time.time() < deadline:
        body = tc.get("/api/refresh/status").json()
        if body["stage"] == "error":
            break
        time.sleep(0.02)
    assert body["stage"] == "error"
    assert "source exploded" in body["error"]
    assert body["running"] is False
