import json

import pytest
from fastapi.testclient import TestClient

from job_dashboard import change_entities, config
from job_dashboard.api import setup_routes
from job_dashboard.api.app import create_app
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing

AGENT = {"X-Agent-Session": "s1", "X-Agent-Message": "m1"}


@pytest.fixture
def env(tmp_path, monkeypatch, fake_embed):
    db = str(tmp_path / "jobs.db")
    c = init_db(db)
    insert_job(c, JobListing(source="s", title="ML", company="Acme", job_url="https://x/1", description="jd"))
    c.close()
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setitem(change_entities.FILES, "candidate_profile", lambda: tmp_path / "profile.local.md")
    monkeypatch.setitem(change_entities.FILES, "setup_state", lambda: tmp_path / "setup-state.md")
    monkeypatch.setattr(setup_routes, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setenv("CURRENT_RESUME_PDF", str(tmp_path / "resume.pdf"))
    for k in setup_routes.SECRET_KEYS:
        monkeypatch.delenv(k, raising=False)
    return TestClient(create_app(db_path=db, qa_embed=fake_embed)), tmp_path


def changes(c, **q):
    return c.get("/api/changes", params=q).json()["changes"]


def test_a_ui_write_is_logged_and_undo_restores_it(env):
    c, _ = env
    c.put("/api/application-profile", json={"phone": "111"})
    c.put("/api/application-profile", json={"phone": "222"})
    last = changes(c)[0]
    assert (last["actor"], last["entity"], last["field"], last["before"], last["after"]) == \
        ("ui", "profile", "phone", "111", "222")
    assert c.post(f"/api/changes/{last['id']}/undo").json()["ok"] is True
    assert c.get("/api/application-profile").json()["phone"] == "111"
    undo_row = changes(c)[0]
    assert undo_row["undo_of"] == last["id"] and undo_row["after"] == "111"
    assert c.post(f"/api/changes/{last['id']}/undo").status_code == 409          # once only


def test_an_agent_write_carries_its_session_and_message_and_reports_the_change(env):
    c, _ = env
    r = c.put("/api/application-profile", json={"location": "Noida"}, headers=AGENT)
    shown = json.loads(r.headers["x-changes"])
    assert [(x["entity"], x["field"], x["after"]) for x in shown] == [("profile", "location", "Noida")]
    row = changes(c, session_id="s1")[0]
    assert (row["actor"], row["session_id"], row["message_id"], row["id"]) == ("agent", "s1", "m1", shown[0]["id"])


def test_an_unchanged_value_logs_nothing(env):
    c, _ = env
    c.put("/api/application-profile", json={"phone": "1"})
    n = len(changes(c))
    c.put("/api/application-profile", json={"phone": "1"})
    assert len(changes(c)) == n


def test_bank_answer_job_fields_and_config_undo(env):
    c, _ = env
    entry = c.get("/api/answers").json()["answers"][0]["id"]
    c.put("/api/answers", json={"entry_id": entry, "answer": "Yes"})
    c.put("/api/answers", json={"entry_id": entry, "answer": "No"})
    c.post(f"/api/changes/{changes(c)[0]['id']}/undo")
    assert next(a for a in c.get("/api/answers").json()["answers"] if a["id"] == entry)["answer"] == "Yes"

    c.delete("/api/answers", params={"entry_id": entry})
    assert entry not in [a["id"] for a in c.get("/api/answers").json()["answers"]]
    c.post(f"/api/changes/{changes(c)[0]['id']}/undo")
    assert entry in [a["id"] for a in c.get("/api/answers").json()["answers"]]

    c.patch("/api/jobs/1/status", json={"status": "applied"})
    c.post(f"/api/changes/{changes(c)[0]['id']}/undo")
    assert c.get("/api/jobs/1").json()["status"] is None

    c.put("/api/jobs/1/apply-details", json={"referrer": "Asha"})
    c.post(f"/api/changes/{changes(c)[0]['id']}/undo")
    assert c.get("/api/jobs/1").json()["apply_details"] == {}

    c.put("/api/config/LLM_MODEL", json={"value": "m2"})
    c.post(f"/api/changes/{changes(c)[0]['id']}/undo")
    assert config.stored().get("LLM_MODEL") is None


def test_a_new_bank_entry_is_retired_on_undo(env):
    c, _ = env
    eid = c.put("/api/answers", json={"question": "Do you like tea?", "answer": "Yes"}).json()["id"]
    c.post(f"/api/changes/{changes(c)[0]['id']}/undo")
    assert eid not in [a["id"] for a in c.get("/api/answers").json()["answers"]]


def test_whole_files_are_logged_and_undo_restores_or_removes_them(env):
    c, tmp = env
    assert c.get("/api/candidate-profile").json() == {"exists": False, "text": ""}
    c.put("/api/candidate-profile", json={"text": "# Me\nv1"})
    c.put("/api/candidate-profile", json={"text": "# Me\nv2"})
    c.post(f"/api/changes/{changes(c)[0]['id']}/undo")
    assert (tmp / "profile.local.md").read_text() == "# Me\nv1"
    c.post(f"/api/changes/{changes(c)[2]['id']}/undo")                       # the very first write
    assert not (tmp / "profile.local.md").exists()

    c.put("/api/setup-state", json={"text": "status: partial\ninit_version: 3\n"})
    assert c.get("/api/setup-state").json()["status"] == "partial"


def test_other_writes_are_logged_as_actions_that_cannot_be_undone(env):
    c, _ = env
    c.post("/api/jobs/1/feedback", json={"verdict": "more", "reasons": []})
    row = changes(c)[0]
    assert (row["entity"], row["entity_id"], row["field"], row["undoable"]) == ("action", "/api/jobs/1/feedback", "POST", False)
    assert c.post(f"/api/changes/{row['id']}/undo").status_code == 409


def test_secrets_go_to_env_and_never_into_the_log_or_back_out(env):
    c, tmp = env
    assert c.get("/api/secrets").json()["secrets"]["LLM_API_KEY"] is False
    assert c.put("/api/secrets/LLM_API_KEY", json={"value": "sk-test-123"}, headers=AGENT).status_code == 403
    (tmp / ".env").write_text("LLM_MODEL=x\nLLM_API_KEY=old\n")
    assert c.put("/api/secrets/LLM_API_KEY", json={"value": "sk-test-123"}).json() == {"key": "LLM_API_KEY", "set": True}
    assert (tmp / ".env").read_text() == "LLM_MODEL=x\nLLM_API_KEY=sk-test-123\n"
    listed = c.get("/api/secrets").json()
    assert listed["secrets"]["LLM_API_KEY"] is True and "sk-test-123" not in json.dumps(listed)
    assert "sk-test-123" not in json.dumps(changes(c))
    assert changes(c)[0]["after"] == "set"
    assert c.put("/api/secrets/NOPE", json={"value": "x"}).status_code == 404


def test_resume_upload_is_human_only_and_must_be_a_pdf(env):
    c, tmp = env
    assert c.put("/api/current-resume", content=b"%PDF-1.4 x", headers=AGENT).status_code == 403
    assert c.put("/api/current-resume", content=b"hello").status_code == 422
    assert c.put("/api/current-resume", content=b"%PDF-1.4 x").json() == {"uploaded": True, "bytes": 10}
    assert (tmp / "resume.pdf").read_bytes() == b"%PDF-1.4 x"


def test_the_agent_needs_a_human_confirmed_single_use_token_for_consequential_actions(env):
    c, _ = env
    entry = c.get("/api/answers").json()["answers"][0]["id"]
    path = f"/api/answers?entry_id={entry}"
    blocked = c.delete(path, headers=AGENT)
    assert blocked.status_code == 403 and blocked.json()["needs_confirmation"] is True

    conf = c.post("/api/confirmations", json={"method": "DELETE", "path": path, "summary": "Retire it"}, headers=AGENT).json()
    assert conf["status"] == "pending" and conf["session_id"] == "s1"
    assert c.post(f"/api/confirmations/{conf['id']}/confirm", headers=AGENT).status_code == 403   # the agent can't
    token = c.post(f"/api/confirmations/{conf['id']}/confirm").json()["token"]
    assert c.delete(f"/api/answers?entry_id=other", headers={**AGENT, "X-Confirm-Token": token}).status_code == 403
    assert c.delete(path, headers={**AGENT, "X-Confirm-Token": token}).status_code == 200
    assert c.delete(path, headers={**AGENT, "X-Confirm-Token": token}).status_code == 403        # used up


def test_ui_requests_need_no_token_and_plain_writes_need_no_confirmation(env):
    c, _ = env
    entry = c.get("/api/answers").json()["answers"][0]["id"]
    assert c.delete("/api/answers", params={"entry_id": entry}).status_code == 200
    r = c.post("/api/confirmations", json={"method": "PUT", "path": "/api/application-profile", "summary": "x"}, headers=AGENT)
    assert r.status_code == 422


def test_a_cancelled_confirmation_issues_no_token(env):
    c, _ = env
    conf = c.post("/api/confirmations", json={"method": "POST", "path": "/api/refresh", "summary": "Refresh"}, headers=AGENT).json()
    assert c.post(f"/api/confirmations/{conf['id']}/cancel").json()["token"] is None
    assert c.post(f"/api/confirmations/{conf['id']}/confirm").status_code == 409
