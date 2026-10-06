import json

from job_dashboard.apply import queue as q

from fastapi.testclient import TestClient

from job_dashboard.api.app import create_app
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing


def _client(tmp_path, launch=None, n=3):
    db = str(tmp_path / "t.db")
    c = init_db(db)
    for i in range(n):
        insert_job(c, JobListing(source="s", title=f"Job {i}", company="Acme",
                                 job_url=f"https://www.naukri.com/job-listings-{i}", description="jd"))
    ids = [r[0] for r in c.execute("SELECT id FROM jobs ORDER BY id")]
    c.close()
    return TestClient(create_app(db_path=db, queue_launch=launch)), ids, db


def _rows(db):
    """Every queue row incl. finished ones — the dashboard list drops those (they are on the tracker)."""
    conn = init_db(db)
    try:
        return {r["job_id"]: (r["state"], r["reason"]) for r in q.list_queue(conn, finished=True)}
    finally:
        conn.close()


def _ids(client):
    return [i["job_id"] for i in client.get("/api/queue").json()["items"]]


def test_add_list_move_remove(tmp_path):
    c, (a, b, d), _ = _client(tmp_path)
    for j in (a, b, d):
        assert c.post("/api/queue", json={"job_id": j}).status_code == 200
    body = c.get("/api/queue").json()
    assert [i["job_id"] for i in body["items"]] == [a, b, d]
    assert body["items"][0]["title"] == "Job 0" and body["items"][0]["state"] == "queued"
    assert body["running"] is False
    c.post(f"/api/queue/{d}/move", json={"before": a})
    assert _ids(c) == [d, a, b]
    c.post(f"/api/queue/{d}/move", json={"before": None})
    assert _ids(c) == [a, b, d]
    assert c.delete(f"/api/queue/{b}").status_code == 200
    assert _ids(c) == [a, d]


def test_add_unknown_job_is_404_and_queued_job_is_saved_to_tracker(tmp_path):
    c, (a, *_), db = _client(tmp_path)
    assert c.post("/api/queue", json={"job_id": 999}).status_code == 404
    c.post("/api/queue", json={"job_id": a})
    assert init_db(db).execute("SELECT status FROM jobs WHERE id = ?", (a,)).fetchone()[0] == "saved"


def test_apply_now_jumps_the_queue_and_starts(tmp_path):
    ran = []

    def launch(job_id, argv, result_path):
        ran.append(job_id)
        with open(result_path, "w") as fh:
            json.dump({"submitted": False, "stopped_reason": "ready_for_review"}, fh)
        return 0

    c, (a, b, _), db = _client(tmp_path, launch=launch, n=3)
    c.post("/api/queue", json={"job_id": a})
    r = c.post("/api/queue", json={"job_id": b, "front": True, "start": True})
    assert r.status_code == 200
    app = c.app
    app.state.queue_runner._thread.join(timeout=5)
    assert ran == [b, a]
    assert _rows(db)[b] == ("parked", "review")
    assert _ids(c) == []                                         # both ran -> off the queue, on the tracker


def test_start_and_pause(tmp_path):
    c, (a, *_), db = _client(tmp_path, launch=lambda j, argv, p: 0)
    c.post("/api/queue", json={"job_id": a})
    assert c.post("/api/queue/pause").json()["paused"] is True
    assert c.post("/api/queue/start").status_code == 200
    c.app.state.queue_runner._thread.join(timeout=5)
    assert _rows(db)[a][0] == "failed"                                       # no result file
    assert _ids(c) == []


def test_autosubmit_toggles(tmp_path):
    c, *_ = _client(tmp_path)
    got = c.get("/api/queue/autosubmit").json()
    assert got["naukri"] is False and got["career_site"] is False and "wellfound" in got
    assert c.put("/api/queue/autosubmit", json={"board": "naukri", "on": True}).json()["naukri"] is True
    assert c.get("/api/queue/autosubmit").json()["naukri"] is True
    assert c.put("/api/queue/autosubmit", json={"board": "nope", "on": True}).status_code == 422


def test_agent_launch_waits_for_a_busy_agent_then_returns_its_exit_code(monkeypatch):
    from types import SimpleNamespace as NS

    import career_agent.config.settings as settings
    from job_dashboard.api.queue_routes import make_agent_launch
    monkeypatch.setattr(settings, "load_settings", lambda: NS(cdp_url=None))

    class State:
        tries = 0

        def start(self, job_id, cmd, cwd, env, log_path):
            State.tries += 1
            self.cmd = cmd
            return State.tries >= 2               # busy once, then free

        def poll(self):
            return {"running": False}             # exits at once -> the stall watchdog has nothing to watch

        def stop(self):
            pass

        def wait(self):
            return 3

    state = State()
    assert make_agent_launch(state, poll_s=0)(7, ["python", "-m", "career_agent.apply"], "/tmp/r.json") == 3
    assert State.tries == 2 and state.cmd[-1] == "career_agent.apply"


def test_telegram_wait_setting_roundtrip_and_bounds(tmp_path):
    c, *_ = _client(tmp_path)
    assert c.get("/api/queue/settings").json() == {"telegram_wait_minutes": 10, "gmail_confirmation_check": False}
    assert c.put("/api/queue/settings", json={"telegram_wait_minutes": 25}).status_code == 200
    assert c.get("/api/queue/settings").json()["telegram_wait_minutes"] == 25
    assert c.put("/api/queue/settings", json={"telegram_wait_minutes": 500}).status_code == 422
    assert c.put("/api/queue/settings", json={"telegram_wait_minutes": -1}).status_code == 422
    # the Gmail confirmation lookup is off until switched on, is switched independently, and can be switched off again
    assert c.put("/api/queue/settings", json={"gmail_confirmation_check": True}).json() == {"telegram_wait_minutes": 25, "gmail_confirmation_check": True}
    assert c.put("/api/queue/settings", json={"gmail_confirmation_check": False}).json()["gmail_confirmation_check"] is False


def test_reconcile_endpoint_needs_the_gmail_switch_and_validates_days(tmp_path, monkeypatch):
    c, (a, b, d), db = _client(tmp_path)
    assert c.post("/api/applied/reconcile", json={}).status_code == 409                     # switch off: no Gmail access at all
    assert c.put("/api/queue/settings", json={"gmail_confirmation_check": True}).status_code == 200
    assert c.post("/api/applied/reconcile", json={"days": 0}).status_code == 422
    mails = [{"id": "m1", "subject": "Your application was sent to Acme", "from": "jobs-noreply@linkedin.com", "snippet": "",
              "date": "2026-10-05T10:00:00+00:00"}]
    monkeypatch.setattr("career_agent.integrations.gmail_confirm.list_confirmations", lambda after, n=100: mails)
    out = c.post("/api/applied/reconcile", json={"days": 14}).json()
    assert out["emails"] == 1 and out["matched"] == [] and len(out["ambiguous"]) == 1       # Acme has 3 tracked jobs: not guessed
