"""Agent-driven apply runs (spec 2026-10-11): the session service's rules, with the page steps faked (no browser)."""
import json

import pytest

from career_agent.browser.form_model import Field
from career_agent.orchestrator.mapper import FillDecision
from career_agent.orchestrator.qa_recorder import QARecorder
from job_dashboard import autonomy, notifications, qa_store
from job_dashboard.apply import queue as q
from job_dashboard.apply import run_store
from job_dashboard.apply import session_steps as steps
from job_dashboard.apply.agent_launch import queue_verdict, run_with_agent
from job_dashboard.apply.session_actor import InlineActor
from job_dashboard.apply.session_service import ApplySessionError, ApplySessions
from job_dashboard.db import init_db

FIELDS = [Field("#name", "text", "Full name", True, [], None, "full_name"),
          Field("#why", "textarea", "Why do you want to work here?", True, [], None, None),
          Field("#ctc", "text", "Expected CTC", True, [], None, None),
          Field("#acct", "text", "Bank account number", True, [], None, None)]


class FakePage:
    def __init__(self, url):
        self.url, self.closed = url, False

    def close(self):
        self.closed = True


@pytest.fixture
def svc(tmp_path, monkeypatch):
    path = str(tmp_path / "jobs.db")
    conn = init_db(path)
    for i in range(1, 9):
        conn.execute("INSERT INTO jobs (id, title, company, job_url, source, description, fetched_at)"
                     " VALUES (?, 'ML Engineer', ?, ?, 'linkedin', '', 'now')", (i, f"Co{i}", f"https://jobs.example/{i}"))
        q.enqueue(conn, i)
    conn.commit()
    conn.close()
    put_calls = []

    def fake_start(s, context):
        s.page = FakePage(s.url)
        return {"url": s.url, "board": None, "entry": "form"}

    def fake_snapshot(s):
        s.fields = {f"f{i}": f for i, f in enumerate(FIELDS, 1)}
        s.suggest = {"f1": FillDecision("#name", "text", "Full name", "Asha Rao", "fill", "profile")}
        return {"step": s.step, "url": s.page.url, "fields": [{"id": k, "label": f.label, "kind": f.kind,
                                                                "required": f.required} for k, f in s.fields.items()]}
    monkeypatch.setattr(steps, "start", fake_start)
    monkeypatch.setattr(steps, "snapshot", fake_snapshot)
    monkeypatch.setattr(steps, "put", lambda s, ds: put_calls.append(ds))
    monkeypatch.setattr(steps, "did_not_stick", lambda s, ds: [])
    monkeypatch.setattr(steps, "submit_click", lambda s: (True, "the page confirmed it"))
    ctx_factory = lambda c, job_id: ({"profile": None, "resume_pdf": None, "job": {}}, QARecorder(c, job_id))
    pushed = []
    service = ApplySessions(path, InlineActor(context=None), ctx_factory=ctx_factory, notify_push=pushed.append)
    service.test_put_calls, service.test_pushed = put_calls, pushed
    yield service
    if service._active is not None:
        service._release(service._active)          # the file lock is per process: free it for the next test


def _ready(svc, job_id=1):
    svc.start(job_id)
    svc.snapshot(job_id)


def test_fill_needs_a_citation_unless_the_agent_marks_the_answer_as_its_own(svc):
    _ready(svc)
    out = svc.fill(1, [{"id": "f3", "value": "25 LPA", "source": "profile"},
                       {"id": "f2", "value": "I build ranking systems.", "source": "agent"},
                       {"id": "f4", "value": "12345", "source": "agent"}], accept_suggestions=True)
    rejected = {r["id"]: r["why"] for r in out["rejected"]}
    assert set(rejected) == {"f3", "f4"} and "cite" in rejected["f3"] and "never" in rejected["f4"]
    assert out["applied"] == 2                                    # the profile suggestion + the agent's own answer
    conn = init_db(svc.db_path)
    rows = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT label, agent_written, source FROM application_qa")}
    assert rows["Why do you want to work here?"] == (1, "agent")
    assert rows["Full name"] == (0, "profile")
    assert "Bank account number" not in rows


def test_a_cited_answer_keeps_its_citation(svc):
    _ready(svc)
    svc.fill(1, [{"id": "f3", "value": "25 LPA", "source": "profile", "citation": "profile.salary_expectation"}])
    conn = init_db(svc.db_path)
    cite = conn.execute("SELECT citation, agent_written FROM application_qa WHERE label='Expected CTC'").fetchone()
    assert json.loads(cite[0]) == {"note": "profile.salary_expectation"} and cite[1] == 0


def test_a_dream_job_holds_submit_when_the_agent_wrote_an_answer(svc):
    conn = init_db(svc.db_path)
    qa_store.set_setting(conn, "autosubmit_career_site", "1")
    qa_store.set_setting(conn, "autosubmit_skip_first_site", "1")
    run_store.set_priority(conn, 1, "dream")
    _ready(svc)
    svc.fill(1, [{"id": "f2", "value": "I build ranking systems.", "source": "agent"}], accept_suggestions=True)
    out = svc.submit(1)
    assert out["held"] and any("not your words" in r for r in out["reasons"])
    assert svc.sessions[1].page is not None                       # nothing clicked, tab still there


def test_a_normal_job_submits_and_marks_the_agent_written_answer(svc):
    conn = init_db(svc.db_path)
    qa_store.set_setting(conn, "autosubmit_career_site", "1")
    qa_store.set_setting(conn, "autosubmit_skip_first_site", "1")
    _ready(svc)
    svc.fill(1, [{"id": "f2", "value": "I build ranking systems.", "source": "agent"}], accept_suggestions=True)
    out = svc.submit(1)
    assert out["submitted"]
    conn = init_db(svc.db_path)
    assert run_store.get(conn, 1)["state"] == "submitted"
    assert conn.execute("SELECT status FROM jobs WHERE id=1").fetchone()[0] == "applied"
    card = notifications.listing(conn)[0]
    assert card["kind"] == "submitted" and "Why do you want to work here?" in card["body"]


def test_submit_is_refused_when_the_switch_is_off(svc):
    _ready(svc)
    out = svc.submit(1)
    assert out["held"] and any("auto-submit is off" in r for r in out["reasons"])


def test_a_captcha_skips_the_run_with_its_reason(svc, monkeypatch):
    monkeypatch.setattr(steps, "reach", lambda s: {"blocked": "captcha", "detail": "recaptcha_v2_checkbox"})
    svc.start(1)
    out = svc.reach(1)
    assert out["skipped"]
    conn = init_db(svc.db_path)
    row = run_store.get(conn, 1)
    assert (row["state"], row["reason"], row["tab_open"]) == ("skipped", "captcha", 0)
    assert 1 not in svc.sessions and svc._active is None           # tab closed, browser free for the next job


def test_pause_keeps_the_tab_and_the_sixth_closes_the_oldest(svc):
    pages = []
    for job in range(1, 7):
        _ready(svc, job)
        pages.append(svc.sessions[job].page)
        svc.pause(job, "needs_answers", "CTC is missing", [{"id": "f3", "why": "never given"}])
    conn = init_db(svc.db_path)
    assert pages[0].closed and not any(p.closed for p in pages[1:])
    assert run_store.get(conn, 1)["tab_open"] == 0 and run_store.get(conn, 6)["tab_open"] == 1
    assert [r["job_id"] for r in run_store.open_paused(conn)] == [2, 3, 4, 5, 6]
    card = notifications.listing(conn)[0]
    assert card["kind"] == "parked" and "Expected CTC" in card["body"] and card["data"]["live"]
    assert qa_store.open_questions(conn, 6)[0]["label"] == "Expected CTC"
    assert svc.test_pushed and "CTC is missing" in svc.test_pushed[-1]


def test_a_paused_run_resumes_in_its_open_tab(svc):
    _ready(svc)
    page = svc.sessions[1].page
    svc.pause(1, "needs_answers", "", [])
    out = svc.start(1)
    assert out["resumed"] and svc.sessions[1].page is page


def test_one_run_at_a_time(svc):
    svc.start(1)
    with pytest.raises(ApplySessionError) as e:
        svc.start(2)
    assert e.value.status == 409


def test_agent_mode_report_grounded_vs_written():
    import sqlite3
    c = sqlite3.connect(":memory:")
    autonomy.ensure(c)
    ds = [{"ref": "a", "label": "Email", "value": "x", "source": "profile"},
          {"ref": "b", "label": "Why us", "value": "y", "source": "agent"},
          {"ref": "c", "label": "Notice", "value": "30", "source": "qbank"}]
    soft = autonomy.autonomy_report(c, "r", ds, agent_mode=True, hold=False)
    hard = autonomy.autonomy_report(c, "r", ds, agent_mode=True, hold=True)
    assert soft["ok"] and soft["agent_written"] == ["Why us"]
    assert not hard["ok"] and [b[0] for b in hard["blockers"]] == ["Why us"]


def test_the_queue_hands_a_job_to_the_agent_and_records_its_verdict():
    calls, rows = [], iter([{"updated_at": "t0"}, {"updated_at": "t1", "state": "running"},
                            {"updated_at": "t2", "state": "paused", "reason": "needs_answers"}])

    def http(method, url, body=None):
        calls.append((method, url))
        return {"session": "s1"} if url.endswith("/agent/runs") else next(rows)
    row = run_with_agent(7, http=http, sleep=lambda s: None)
    assert row["state"] == "paused" and row["agent_session"] == "s1"
    assert ("POST", "http://127.0.0.1:8000/agent/runs") in calls
    assert queue_verdict(row) == ("parked", "needs_answers")
    assert queue_verdict({"state": "submitted"}) == ("done", None)
    assert queue_verdict({"state": "skipped", "reason": "captcha"}) == ("failed", "captcha")


def test_a_parked_agent_run_with_its_tab_open_is_watched_for_a_submit(tmp_path):
    from job_dashboard.apply.queue_runner import QueueRunner
    conn = init_db(str(tmp_path / "jobs.db"))
    conn.execute("INSERT INTO jobs (id, source, title, company, job_url, description, fetched_at) VALUES (5, 't', 'ML', 'Co', 'https://co/5', 'd', 'now')")
    conn.commit()
    watched = []

    class Watcher:
        def register(self, conn, job_id, url, run_key, tab_id, how):
            watched.append((job_id, tab_id, how))
    runner = QueueRunner(str(tmp_path / "jobs.db"), launch=None, watcher=Watcher())
    runner.agent_run = lambda job_id: {"state": "paused", "reason": "submit_unconfirmed", "tab_open": 1,
                                       "tab_target_id": "T1", "url": "https://co/5", "run_key": "r"}
    runner._run_agent(conn, 5)
    runner.agent_run = lambda job_id: {"state": "paused", "reason": "review", "tab_open": 0, "tab_target_id": "T2"}
    runner._run_agent(conn, 5)
    assert watched == [(5, "T1", "auto")]


def test_routes_start_only_a_queued_job_and_priority_has_undo(svc):
    from fastapi.testclient import TestClient
    from job_dashboard.api.app import create_app
    client = TestClient(create_app(db_path=svc.db_path, apply_sessions=svc))
    conn = init_db(svc.db_path)
    q.remove(conn, 8)
    assert client.post("/api/apply-sessions/8").status_code == 409            # not queued: queueing is what you Confirm
    assert client.post("/api/apply-sessions/1").json()["url"] == "https://jobs.example/1"
    assert client.put("/api/jobs/2/priority", json={"level": "galaxy"}).status_code == 422
    r = client.put("/api/jobs/2/priority", json={"level": "dream"})
    assert r.status_code == 200 and client.get("/api/apply-sessions/2").json()["priority"] == "dream"
    change = client.get("/api/changes").json()["changes"][0]
    assert client.post(f"/api/changes/{change['id']}/undo").status_code == 200
    assert client.get("/api/apply-sessions/2").json()["priority"] == "normal"
    agent = {"x-agent-session": "s", "x-agent-message": "m"}
    assert client.post("/api/apply-sessions/1/resume", headers=agent).status_code == 403   # Resume is yours


def test_queue_settings_set_the_apply_engine_and_holds(svc):
    from fastapi.testclient import TestClient
    from job_dashboard.api.app import create_app
    client = TestClient(create_app(db_path=svc.db_path, apply_sessions=svc))
    assert client.put("/api/queue/settings", json={"apply_engine": "robot"}).status_code == 422
    assert client.put("/api/queue/settings", json={"apply_hold_priorities": ["dream", "meh"]}).status_code == 422
    r = client.put("/api/queue/settings", json={"apply_engine": "agent", "apply_hold_priorities": ["dream"],
                                                "autosubmit_skip_first_site": True}).json()
    assert (r["apply_engine"], r["apply_hold_priorities"], r["autosubmit_skip_first_site"]) == ("agent", "dream", "1")
    agent = {"x-agent-session": "s", "x-agent-message": "m"}
    assert client.put("/api/queue/settings", json={"apply_engine": "script"}, headers=agent).status_code == 403


def test_the_tab_the_form_opened_in_is_saved_for_resume_and_the_submit_watch(svc, monkeypatch):
    def hop(s):
        s.tab_target_id = "FORM-TAB"
        return {"on_form": True}
    monkeypatch.setattr(steps, "reach", hop)
    svc.start(1)
    svc.reach(1)
    conn = init_db(svc.db_path)
    assert run_store.get(conn, 1)["tab_target_id"] == "FORM-TAB"
    svc.pause(1, "review", "check it", [])
    assert run_store.get(conn, 1)["tab_target_id"] == "FORM-TAB"


def test_a_finished_run_closes_the_listing_tab_and_the_form_tab(svc, monkeypatch):
    form = FakePage("https://ats.example/apply")

    def hop(s):
        s.page = form
        return {"on_form": True}
    monkeypatch.setattr(steps, "reach", hop)
    svc.start(1)
    listing = svc.sessions[1].page
    svc.reach(1)
    svc.skip(1, "captcha", "a captcha on the form")
    assert listing.closed and form.closed


def test_skipping_twice_leaves_one_card(svc, monkeypatch):
    monkeypatch.setattr(steps, "reach", lambda s: {"blocked": "captcha"})
    svc.start(1)
    svc.reach(1)
    assert svc.skip(1, "captcha", "again")["note"].startswith("already skipped")
    conn = init_db(svc.db_path)
    assert len(notifications.listing(conn)) == 1


def test_a_dialog_reaches_the_agent_and_its_button_is_pressed(svc, monkeypatch):
    pressed = []
    monkeypatch.setattr(steps, "press_dialog", lambda s, b: pressed.append(b) or {"pressed": b})
    _ready(svc)
    out = svc.dialog(1, "Decline")
    assert pressed == ["Decline"] and out["pressed"] == "Decline" and out["page"]["fields"]


def test_a_refused_dialog_button_is_a_readable_error(svc, monkeypatch):
    def refuse(s, b):
        raise steps.StepError("Sign up can't be pressed from a dialog")
    monkeypatch.setattr(steps, "press_dialog", refuse)
    _ready(svc)
    with pytest.raises(ApplySessionError) as e:
        svc.dialog(1, "Sign up")
    assert e.value.status == 422


def test_the_resume_step_uploads_the_current_resume_rather_than_picking_an_old_one():
    from types import SimpleNamespace
    files = ["Aditya Kumar 24 resume.pdf", "Aditya_Kumar_Resume.pdf", "Aditya_Kumar_Resume.pdf"]
    cv = Field("group:cv", "radio_group", "Resume", False, files, None, None)
    s = SimpleNamespace(ctx={"resume_pdf": "/data/resumes/upload/Aditya_Kumar_Resume.pdf"})
    upload = steps._resume_upload([cv], ["Upload resume", "Back", "Next"])
    assert [(f.ref, f.kind) for f in upload] == [("button:Upload resume", "file")]
    picks = steps._resume_choices(s, [cv, *upload])
    assert [(d.ref, d.action, d.value) for d in picks] == [("button:Upload resume", "upload_chooser",
                                                            "/data/resumes/upload/Aditya_Kumar_Resume.pdf")]
    assert steps.decision_for(s, upload[0], "resume", "resume").action == "upload_chooser"
    # no upload button: pick by name only when exactly one entry has it
    assert steps._resume_choices(s, [cv]) == []
    one = Field("group:cv", "radio_group", "Resume", False, ["Old.pdf", "Aditya_Kumar_Resume.pdf"], None, None)
    assert [d.value for d in steps._resume_choices(s, [one])] == ["Aditya_Kumar_Resume.pdf"]
    assert steps._resume_upload([Field("group:q", "radio_group", "Relocate?", True, ["Yes", "No"])], ["Upload resume"]) == []
