import threading
import time

import pytest
from fastapi.testclient import TestClient

from job_dashboard.api.app import create_app
from job_dashboard.linkedin.hiring_refresh import HiringRefresh, RefreshBusy


def test_runs_once_at_a_time_and_reports_progress():
    r, gate = HiringRefresh(), threading.Event()

    def run(on_event):
        on_event({"stage": "search", "i": 1, "n": 8, "kept": 0})
        gate.wait(5)
        on_event({"stage": "done", "kept": 3})
    r.start(run)
    assert r.status()["state"] == "running"
    with pytest.raises(RefreshBusy):
        r.start(run)
    gate.set()
    for _ in range(50):
        if not r.running():
            break
        time.sleep(0.05)
    assert r.status()["state"] == "done" and r.status()["kept"] == 3 and r.status()["finished_at"]


def test_error_lands_in_status_not_in_the_thread():
    r = HiringRefresh()

    def boom(on_event):
        raise ValueError("nope")
    s = r.start(boom, wait=True)
    assert s["state"] == "error" and s["error"] == "nope" and s["error_type"] == "ValueError"
    r.start(lambda e: None, wait=True)                       # a failed run does not block the next one
    assert r.status()["state"] == "done"


class _Fetcher:
    def __init__(self, gate=None): self.gate = gate

    def search_posts(self, kw, **k):
        if self.gate:
            self.gate.wait(5)
        return [{"url": f"u-{kw}", "poster_name": "Jane", "poster_headline": "HR",
                 "text": f"Hiring an ML Engineer ({kw})", "posted_at": "1h"}]


def test_background_refresh_api(tmp_path):
    gate = threading.Event()
    c = TestClient(create_app(db_path=str(tmp_path / "t.db"), hiring_fetcher=_Fetcher(gate), embed_model=None,
                              hiring_role_fn=lambda p: {"title": "ML Engineer", "fit": 90, "reason": "r"}))
    r = c.post("/api/hiring/refresh?background=true").json()
    assert r["started"] is True and r["state"] == "running"
    assert c.post("/api/hiring/refresh?background=true").json()["started"] is False      # already going
    assert c.post("/api/hiring/refresh").status_code == 409                               # blocking mode refuses too
    gate.set()
    for _ in range(100):
        st = c.get("/api/hiring/refresh/status").json()
        if st["state"] != "running":
            break
        time.sleep(0.05)
    assert st["state"] == "done" and st["kept"] >= 1 and st["found"] >= 1
    assert len(c.get("/api/hiring/posts").json()["posts"]) >= 1


def test_status_is_idle_before_any_run(tmp_path):
    c = TestClient(create_app(db_path=str(tmp_path / "t.db"), embed_model=None))
    assert c.get("/api/hiring/refresh/status").json() == {"state": "idle"}
    assert c.post("/api/hiring/refresh?background=true").status_code == 503              # no fetcher configured
