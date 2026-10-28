"""The Inbox: questions blocking applications, guesses to confirm, profile readiness, snoozing, and run updates."""
import pytest
from fastapi.testclient import TestClient

from job_dashboard import notifications, qa_store
from job_dashboard.api.app import create_app
from job_dashboard.apply.queue_runner import announce
from job_dashboard.apply.store import get_application_profile
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing


@pytest.fixture
def env(tmp_path, fake_embed):
    db = str(tmp_path / "t.db")
    c = init_db(db)
    for i in (1, 2):
        insert_job(c, JobListing(source="s", title=f"Role {i}", company="Acme", location="Pune",
                                 job_url=f"https://x/{i}", description="jd"))
    qa_store.ensure(c)
    c.close()
    llm = lambda prompt: {"answer": "Immediate", "also": {}, "request": None}       # noqa: E731
    return TestClient(create_app(db_path=db, qa_embed=fake_embed, queue_launch=lambda *a: 0, profile_llm=llm)), db


def test_inbox_lists_blocking_questions_with_their_options_and_guesses_to_confirm(env):
    c, db = env
    conn = init_db(db)
    qa_store.record(conn, job_id=2, run_key="r", ref="q1", label="Notice period?", kind="select",
                    status="needs_answer", context_json={"options": ["Immediate", "30 days"]})
    qa_store.record(conn, job_id=2, run_key="r", ref="q2", label="Years of Python?", kind="text",
                    status="filled", source="qbank_likely", answer="5")
    conn.close()
    box = c.get("/api/inbox").json()
    assert [(q["label"], q["options"]) for q in box["questions"]] == [("Notice period?", ["Immediate", "30 days"])]
    assert [(g["label"], g["answer"]) for g in box["guesses"]] == [("Years of Python?", "5")]


def test_a_snoozed_guess_stays_out_of_the_inbox(env):
    c, db = env
    conn = init_db(db)
    qa_store.record(conn, job_id=2, run_key="r", ref="q2", label="Years of Python?", kind="text",
                    status="filled", source="qbank_likely", answer="5")
    conn.close()
    row = c.get("/api/inbox").json()["guesses"][0]["row_id"]
    assert c.post("/api/inbox/snooze", json={"keys": [f"g{row}"]}).json()["snoozed"] == 1
    assert c.get("/api/inbox").json()["guesses"] == []


def test_facts_write_one_profile_column_and_keep_the_rest(env):
    c, db = env
    c.post("/api/profile/facts", json={"answers": {"profile:phone": "+91 99999 00000"}})
    r = c.post("/api/profile/facts", json={"answers": {"profile:willing_to_relocate": "No", "profile:bogus": "x"}}).json()
    assert [w["key"] for w in r["written"]] == ["profile:willing_to_relocate"]
    p = get_application_profile(init_db(db))
    assert p["phone"] == "+91 99999 00000" and p["willing_to_relocate"] is False
    assert "percent" in r["readiness"]


def test_interpret_uses_the_model_and_saves_nothing(env):
    c, _ = env
    r = c.post("/api/answers/interpret", json={"question": "Notice period?", "text": "I can join right away"}).json()
    assert r["answer"] == "Immediate" and r["interpreted"] is True


def test_a_finished_run_lands_in_updates_and_can_be_dismissed(env):
    c, db = env
    conn = init_db(db)
    announce(conn, 1, "parked", "needs_answers")
    announce(conn, 1, "done", None)                      # a newer event about the same job replaces it
    conn.close()
    feed = c.get("/api/notifications").json()
    assert [n["title"] for n in feed["items"]] == ["Applied: Role 1 at Acme"] and feed["unread"] == 1
    nid = feed["items"][0]["id"]
    assert c.post(f"/api/notifications/{nid}/dismiss").json()["unread"] == 0
    assert c.post(f"/api/notifications/{nid}/dismiss").status_code == 404


def test_an_unknown_stop_reason_never_shows_a_raw_code(env):
    _, db = env
    conn = init_db(db)
    announce(conn, 2, "parked", "weird_internal_code")
    assert "weird_internal_code" not in notifications.listing(conn)[0]["title"]
