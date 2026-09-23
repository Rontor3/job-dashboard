import time

from fastapi.testclient import TestClient

from job_dashboard.api import agent_routes
from job_dashboard.api.app import create_app
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing


def _client(tmp_path):
    db = str(tmp_path / "t.db")
    c = init_db(db)
    insert_job(c, JobListing(source="s", title="ML Eng", company="Acme",
                             job_url="https://boards.greenhouse.io/acme/jobs/1", description="jd"))
    jid = c.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
    c.close()
    return TestClient(create_app(db_path=db)), jid


class FakePopen:
    """Stands in for subprocess.Popen: stays 'running' (poll() -> None) until
    .finish(code) is called, so tests control exactly when the agent 'exits'."""
    def __init__(self, *a, **kw):
        self._code = None

    def poll(self):
        return self._code

    def finish(self, code=0):
        self._code = code


def test_launch_missing_job_404(tmp_path):
    c, _ = _client(tmp_path)
    assert c.post("/api/jobs/999/apply-agent").status_code == 404


def test_launch_job_without_url_422(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    insert_job(conn, JobListing(source="s", title="T", company="C",
                                job_url="https://x/1", description="jd"))
    jid = conn.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
    conn.execute("UPDATE jobs SET job_url = '' WHERE id = ?", (jid,))
    conn.commit()
    conn.close()
    c = TestClient(create_app(db_path=db))
    assert c.post(f"/api/jobs/{jid}/apply-agent").status_code == 422


def test_launch_then_status_running_then_done(tmp_path, monkeypatch):
    c, jid = _client(tmp_path)
    fake = {}

    def fake_popen(cmd, cwd=None, env=None, stdout=None, stderr=None):
        p = FakePopen()
        fake["proc"] = p
        fake["cmd"] = cmd
        return p

    monkeypatch.setattr(agent_routes.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        "career_agent.config.settings.load_settings",
        lambda: type("S", (), {"cdp_url": None})(),
    )

    r = c.post(f"/api/jobs/{jid}/apply-agent")
    assert r.status_code == 200
    assert r.json() == {"started": True, "job_id": jid}
    assert "--job-id" in fake["cmd"] and str(jid) in fake["cmd"]
    assert "--submit" not in fake["cmd"]  # this path never auto-submits

    status = c.get("/api/apply-agent/status").json()
    assert status["running"] is True
    assert status["job_id"] == jid
    assert status["url"] is None  # cdp_url is None -> no live read attempted

    fake["proc"].finish(0)
    status = c.get("/api/apply-agent/status").json()
    assert status == {"running": False, "job_id": jid, "status": "done", "exit_code": 0}


def test_launch_409_while_running(tmp_path, monkeypatch):
    c, jid = _client(tmp_path)
    monkeypatch.setattr(agent_routes.subprocess, "Popen", lambda *a, **kw: FakePopen())
    assert c.post(f"/api/jobs/{jid}/apply-agent").status_code == 200
    assert c.post(f"/api/jobs/{jid}/apply-agent").status_code == 409


def test_status_idle_when_nothing_ever_ran(tmp_path):
    c, _ = _client(tmp_path)
    assert c.get("/api/apply-agent/status").json() == {"running": False, "job_id": None}


def test_history_404_when_no_run_exists(tmp_path):
    c, jid = _client(tmp_path)
    assert c.get(f"/api/jobs/{jid}/agent-runs/latest").status_code == 404


def test_history_404_for_missing_job(tmp_path):
    c, _ = _client(tmp_path)
    assert c.get("/api/jobs/999/agent-runs/latest").status_code == 404


def test_live_screenshot_404_when_none_saved(tmp_path):
    c, jid = _client(tmp_path)
    assert c.get(f"/api/jobs/{jid}/agent-runs/live-screenshot").status_code == 404


def test_step_screenshot_404_when_none_saved(tmp_path):
    c, jid = _client(tmp_path)
    assert c.get(f"/api/jobs/{jid}/agent-runs/screenshot/3").status_code == 404


def test_history_rewrites_screenshot_paths_to_urls(tmp_path, monkeypatch):
    c, jid = _client(tmp_path)
    fake_steps = [
        {"step": 1, "kind": "form", "cred_action": None, "stopped_reason": None,
         "pending_human": [], "gate_notice": None, "screenshot": "/abs/path/perceive1.png"},
        {"step": 2, "kind": "form", "cred_action": None, "stopped_reason": "stuck",
         "pending_human": [], "gate_notice": None, "screenshot": None},
    ]
    monkeypatch.setattr(
        "career_agent.orchestrator.run_history.summarize_run",
        lambda thread_id, db_path, run_dir=None: fake_steps,
    )
    r = c.get(f"/api/jobs/{jid}/agent-runs/latest")
    assert r.status_code == 200
    body = r.json()
    assert body["steps"][0]["screenshot"] == f"/api/jobs/{jid}/agent-runs/screenshot/1"
    assert body["steps"][1]["screenshot"] is None
