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


def test_ensure_cdp_chrome_noop_when_already_reachable(monkeypatch):
    monkeypatch.setattr(agent_routes, "_cdp_reachable", lambda url, timeout=1.5: True)
    launched = []
    monkeypatch.setattr(agent_routes, "_launch_cdp_chrome", lambda port: launched.append(port))
    assert agent_routes._ensure_cdp_chrome("http://localhost:9222") is None
    assert launched == []


def test_ensure_cdp_chrome_refuses_to_kill_existing_chrome(monkeypatch):
    monkeypatch.setattr(agent_routes, "_cdp_reachable", lambda url, timeout=1.5: False)
    monkeypatch.setattr(agent_routes, "_any_chrome_running", lambda: True)
    launched = []
    monkeypatch.setattr(agent_routes, "_launch_cdp_chrome", lambda port: launched.append(port))
    problem = agent_routes._ensure_cdp_chrome("http://localhost:9222")
    assert problem is not None
    assert "close your existing Chrome" in problem
    assert launched == []  # never auto-restarts over an existing Chrome


def test_ensure_cdp_chrome_auto_launches_when_nothing_running(monkeypatch):
    calls = {"reachable": 0}

    def fake_reachable(url, timeout=1.5):
        calls["reachable"] += 1
        return calls["reachable"] > 1  # unreachable first call, reachable after "launch"

    launched = []
    monkeypatch.setattr(agent_routes, "_cdp_reachable", fake_reachable)
    monkeypatch.setattr(agent_routes, "_any_chrome_running", lambda: False)
    monkeypatch.setattr(agent_routes, "_launch_cdp_chrome", lambda port: launched.append(port))
    assert agent_routes._ensure_cdp_chrome("http://localhost:9222") is None
    assert launched == [9222]


def test_ensure_cdp_chrome_reports_timeout_if_it_never_comes_up(monkeypatch):
    # first monotonic() call sets the deadline; the second (in the while
    # condition) must already be past it, or this would real-sleep for 10s.
    calls = {"n": 0}
    def fake_monotonic():
        calls["n"] += 1
        return 0 if calls["n"] == 1 else 100
    monkeypatch.setattr(agent_routes, "_cdp_reachable", lambda url, timeout=1.5: False)
    monkeypatch.setattr(agent_routes, "_any_chrome_running", lambda: False)
    monkeypatch.setattr(agent_routes, "_launch_cdp_chrome", lambda port: None)
    monkeypatch.setattr(agent_routes.time, "monotonic", fake_monotonic)
    problem = agent_routes._ensure_cdp_chrome("http://localhost:9222")
    assert problem is not None and "didn't come up" in problem


def test_launch_triggers_cdp_chrome_recovery_and_503s_if_refused(tmp_path, monkeypatch):
    c, jid = _client(tmp_path)
    monkeypatch.setattr(
        "career_agent.config.settings.load_settings",
        lambda: type("S", (), {"cdp_url": "http://localhost:9222"})(),
    )
    monkeypatch.setattr(agent_routes, "_cdp_reachable", lambda url, timeout=1.5: False)
    monkeypatch.setattr(agent_routes, "_any_chrome_running", lambda: True)
    r = c.post(f"/api/jobs/{jid}/apply-agent")
    assert r.status_code == 503
    assert "close your existing Chrome" in r.json()["detail"]


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


def test_log_404_when_none(tmp_path, monkeypatch):
    c, jid = _client(tmp_path)
    monkeypatch.setattr(agent_routes, "REPO_ROOT", tmp_path)
    assert c.get(f"/api/jobs/{jid}/agent-runs/log").status_code == 404


def test_log_returns_tail(tmp_path, monkeypatch):
    c, jid = _client(tmp_path)
    monkeypatch.setattr(agent_routes, "REPO_ROOT", tmp_path)
    p = tmp_path / "data" / "agent_runs"
    p.mkdir(parents=True)
    (p / f"{jid}.log").write_text("\n".join(f"line {i}" for i in range(200)) + "\n")
    r = c.get(f"/api/jobs/{jid}/agent-runs/log?lines=5")
    assert r.status_code == 200
    assert r.json()["lines"] == [f"line {i}" for i in range(195, 200)]


def test_log_clips_huge_lines(tmp_path, monkeypatch):
    c, jid = _client(tmp_path)
    monkeypatch.setattr(agent_routes, "REPO_ROOT", tmp_path)
    p = tmp_path / "data" / "agent_runs"
    p.mkdir(parents=True)
    (p / f"{jid}.log").write_text("short\n" + "x" * 5000 + "\n")
    lines = c.get(f"/api/jobs/{jid}/agent-runs/log").json()["lines"]
    assert lines[0] == "short"
    assert len(lines[1]) < 500 and lines[1].endswith("[+4600 chars]")


def _launch_cmd(tmp_path, monkeypatch, **job_kw):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    insert_job(conn, JobListing(source="s", title="T", company="C",
                                job_url="https://www.linkedin.com/jobs/view/1", description="jd", **job_kw))
    jid = conn.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
    conn.close()
    seen = {}

    def fake_popen(cmd, **kw):
        seen["cmd"] = cmd
        return FakePopen()

    monkeypatch.setattr(agent_routes.subprocess, "Popen", fake_popen)
    monkeypatch.setattr("career_agent.config.settings.load_settings",
                        lambda: type("S", (), {"cdp_url": None})())
    assert TestClient(create_app(db_path=db)).post(f"/api/jobs/{jid}/apply-agent").status_code == 200
    return seen["cmd"]


def test_launch_uses_apply_url_when_external(tmp_path, monkeypatch):
    cmd = _launch_cmd(tmp_path, monkeypatch, apply_kind="external",
                      apply_url="https://boards.greenhouse.io/x/1")
    assert cmd[cmd.index("--url") + 1] == "https://boards.greenhouse.io/x/1"


def test_launch_uses_job_url_without_apply_url(tmp_path, monkeypatch):
    cmd = _launch_cmd(tmp_path, monkeypatch)
    assert cmd[cmd.index("--url") + 1] == "https://www.linkedin.com/jobs/view/1"


def test_history_of_a_board_job_comes_from_board_run_json(tmp_path, monkeypatch):
    import json
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    insert_job(conn, JobListing(source="naukri", title="ML", company="Acme",
                                job_url="https://www.naukri.com/job-listings-1", description="jd"))
    jid = conn.execute("SELECT id FROM jobs").fetchone()[0]
    conn.close()
    monkeypatch.setattr(agent_routes, "REPO_ROOT", tmp_path)
    run_dir = tmp_path / "data" / "agent_runs" / str(jid)
    run_dir.mkdir(parents=True)
    (run_dir / "board_run.json").write_text(json.dumps([
        {"step": 0, "kind": "form", "url": "u", "stopped_reason": None, "pending_human": [],
         "screenshot": str(run_dir / "perceive0.png")},
        {"step": 1, "kind": "stop", "url": "u", "stopped_reason": "needs_human",
         "pending_human": [{"ref": "a", "label": "CTC"}], "screenshot": None}]))
    body = TestClient(create_app(db_path=db)).get(f"/api/jobs/{jid}/agent-runs/latest").json()
    assert [s["stopped_reason"] for s in body["steps"]] == [None, "needs_human"]
    assert body["steps"][0]["screenshot"] == f"/api/jobs/{jid}/agent-runs/screenshot/0"
    assert body["steps"][1]["screenshot"] is None
