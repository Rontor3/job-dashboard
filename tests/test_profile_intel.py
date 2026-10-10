"""Readiness, filling gaps from the user's documents, reading typed answers, and an Inbox that asks only what matters."""
import json

import pytest
from fastapi.testclient import TestClient

from job_dashboard import change_entities, qa_store
from job_dashboard.api.app import create_app
from job_dashboard.db import init_db

RESUME = "Aditya Kumar — Machine Learning Engineer at Rephrase.ai. IIT (BHU) Varanasi, B.Tech + M.Tech, 2024."


@pytest.fixture
def env(tmp_path, monkeypatch, fake_embed):
    db = str(tmp_path / "jobs.db")
    init_db(db).close()
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setenv("CURRENT_RESUME_PDF", str(pdf))
    monkeypatch.setattr("job_dashboard.resume.ats._default_extract", lambda p: RESUME)
    monkeypatch.setitem(change_entities.FILES, "candidate_profile", lambda: tmp_path / "profile.local.md")
    monkeypatch.setitem(change_entities.FILES, "ingredients", lambda: tmp_path / "ingredients.json")
    prompts = []

    def llm(prompt):
        prompts.append(prompt)
        if "typed this" in prompt:
            return {"answer": "Machine Learning Engineer", "also": {"qbank:current_employer": "Rephrase.ai", "qbank:nope": "x"},
                    "request": "Read my title from LinkedIn next time."}
        return {"answers": {"qbank:current_title": "Machine Learning Engineer", "qbank:university": "IIT (BHU) Varanasi",
                            "qbank:graduation_year": "2024", "qbank:highest_degree": "Integrated / dual degree (Bachelor's + Master's)",
                            "qbank:made_up": "ignored"}}

    client = TestClient(create_app(db_path=db, qa_embed=fake_embed, profile_llm=llm, profile_linkedin=lambda: ""))
    return client, db, prompts


def test_readiness_counts_must_haves_and_resume(env):
    c, _, _ = env
    r = c.get("/api/profile/readiness").json()
    assert r["ready"] is False and 0 < r["percent"] < 30          # only the résumé is known
    assert {"key": "qbank:current_title", "label": "Current job title"} in r["required_missing"]
    assert r["autofill_due"] is True


def test_autofill_fills_gaps_from_the_resume_with_undo(env):
    c, _, prompts = env
    out = c.post("/api/profile/autofill", json={}).json()
    assert {f["key"] for f in out["filled"]} == {"qbank:current_title", "qbank:university", "qbank:graduation_year", "qbank:highest_degree"}
    assert "Rephrase.ai" in prompts[0] and "Résumé" in out["sources"]
    assert c.get("/api/profile/readiness").json()["autofill_due"] is False
    answers = {a["id"]: a for a in c.get("/api/answers").json()["answers"]}
    assert answers["university"]["answer"] == "IIT (BHU) Varanasi"
    change = next(x for x in c.get("/api/changes").json()["changes"] if x["entity_id"] == "university")
    c.post(f"/api/changes/{change['id']}/undo")
    assert {a["id"]: a for a in c.get("/api/answers").json()["answers"]}["university"]["answer"] in (None, "")


def test_a_typed_answer_is_cleaned_split_and_its_request_kept_apart(env):
    c, _, _ = env
    r = c.post("/api/answers/interpret", json={"question": "What is your current job title?", "entry_id": "current_title",
               "text": "Machine learning engineer. Why weren't you able to scrape this from my LinkedIn?"}).json()
    assert r["answer"] == "Machine Learning Engineer"
    assert r["also"] == {"qbank:current_employer": "Rephrase.ai"}             # unknown ids dropped
    assert r["request"] == "Read my title from LinkedIn next time." and r["interpreted"] is True
    assert c.post("/api/profile/facts", json={"answers": r["also"]}).json()["written"] == [
        {"key": "qbank:current_employer", "value": "Rephrase.ai"}]


def test_interpret_falls_back_to_the_text_when_the_model_is_down(env, fake_embed, tmp_path):
    def down(_):
        raise ConnectionError("no model")
    c = TestClient(create_app(db_path=env[1], qa_embed=fake_embed, profile_llm=down))
    r = c.post("/api/answers/interpret", json={"question": "Title?", "text": " ML engineer "}).json()
    assert (r["answer"], r["interpreted"]) == ("ML engineer", False)


def test_inbox_skips_common_questions_nobody_asked_and_snoozed_ones(env):
    c, db, _ = env
    bank = {b["id"] for b in c.get("/api/inbox", params={"bank_limit": 50}).json()["bank"]}
    assert "sexual_orientation" not in bank and "transgender" not in bank     # nobody asked; not a must-have
    assert "current_title" in bank                                            # every form needs it
    assert c.post("/api/inbox/snooze", json={"keys": ["bcurrent_title"]}).json()["snoozed"] == 1
    assert "current_title" not in {b["id"] for b in c.get("/api/inbox", params={"bank_limit": 50}).json()["bank"]}
    conn = init_db(db)
    assert "bcurrent_title" in json.loads(qa_store.get_setting(conn, "inbox_snoozed"))
    conn.close()


def test_inbox_asks_profile_must_haves_and_saves_them_to_the_profile(env):
    c, _, _ = env
    bank = {b["id"]: b for b in c.get("/api/inbox", params={"bank_limit": 50}).json()["bank"]}
    notice = bank["profile:notice_period"]
    assert notice["fact"] == "profile:notice_period" and "notice period" in notice["question"]
    c.post("/api/profile/facts", json={"answers": {notice["fact"]: "60 days"}})
    assert "profile:notice_period" not in {b["id"] for b in c.get("/api/inbox", params={"bank_limit": 50}).json()["bank"]}
    assert "profile:notice_period" not in {m["key"] for m in c.get("/api/profile/readiness").json()["required_missing"]}
