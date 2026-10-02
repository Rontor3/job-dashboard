import pytest
from fastapi.testclient import TestClient

from job_dashboard import qa_store
from job_dashboard.api.app import create_app
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing


@pytest.fixture
def env(tmp_path, fake_embed):
    db = str(tmp_path / "t.db")
    c = init_db(db)
    insert_job(c, JobListing(source="s", title="ML Eng", company="Acme",
                             job_url="https://x/1", description="jd"))
    c.close()
    return TestClient(create_app(db_path=db, qa_embed=fake_embed)), db


def _entry(c, eid):
    return next(a for a in c.get("/api/answers").json()["answers"] if a["id"] == eid)


def _open(db, label="Have you used Claude before?", kind="radio_group"):
    conn = init_db(db)
    qa_store.record(conn, job_id=1, run_key="r", ref=label, label=label, kind=kind, status="needs_answer")
    rid = conn.execute("select max(id) from application_qa").fetchone()[0]
    conn.close()
    return rid


def _filled(db, label="How many days is your notice?", matched="notice_period", kind="shortlist"):
    conn = init_db(db)
    qa_store.record(conn, job_id=1, run_key="r", ref="#a", label=label, kind="text", status="filled",
                    answer="30", source="qbank", retrieval_kind=kind, retrieved_qkey=matched,
                    retrieval_score=0.72)
    rid = conn.execute("select max(id) from application_qa").fetchone()[0]
    conn.close()
    return rid


def test_questionnaire_lists_seed_with_unanswered_count(env):
    c, _ = env
    body = c.get("/api/answers").json()
    assert len(body["answers"]) >= 90 and body["unanswered"] > 0
    n = _entry(c, "notice_period")
    assert n["needs_input"] is False and "Notice period" in n["wordings"]
    s = _entry(c, "sponsorship_required")
    assert s["needs_input"] is True and s["value"] is None
    w = _entry(c, "work_location")
    assert w["needs_input"] is False and "relocating" in w["rule_help"]
    assert any(a["id"] == "sponsorship_required" for a in c.get("/api/answers?q=sponsor").json()["answers"])


def test_answer_entry_and_add_new(env):
    c, _ = env
    before = c.get("/api/answers").json()["unanswered"]
    assert c.put("/api/answers", json={"entry_id": "sponsorship_required", "answer": "Yes"}).status_code == 200
    assert _entry(c, "sponsorship_required")["value"] == "Yes"
    assert c.get("/api/answers").json()["unanswered"] == before - 1
    assert c.put("/api/answers", json={"question": "Have you used Claude?", "answer": "Yes"}).json()["id"] == "have_you_used_claude"
    assert c.put("/api/answers", json={"entry_id": "nope", "answer": "x"}).status_code == 404
    assert c.put("/api/answers", json={"answer": "x"}).status_code == 422
    assert c.put("/api/answers", json={"entry_id": "pronouns", "answer": " "}).status_code == 422


def test_delete_supersedes_not_erases(env):
    c, db = env
    assert c.delete("/api/answers", params={"entry_id": "pronouns"}).status_code == 200
    assert all(a["id"] != "pronouns" for a in c.get("/api/answers").json()["answers"])
    conn = init_db(db)
    assert conn.execute("select status from qbank_entry where id='pronouns'").fetchone() == ("superseded",)
    conn.close()
    assert c.delete("/api/answers", params={"entry_id": "nope"}).status_code == 404


def test_entries_search(env):
    c, _ = env
    ids = [e["id"] for e in c.get("/api/qbank/entries?search=notice").json()["entries"]]
    assert "notice_period" in ids and "gender" not in ids


def test_entries_excludes_story_topic(env):
    c, _ = env
    ids = [e["id"] for e in c.get("/api/qbank/entries").json()["entries"]]
    assert "story_why_startups" not in ids


def test_reply_to_likely_row_keeps_source_and_logs_calibration(env):
    c, db = env
    conn = init_db(db)
    qa_store.record(conn, job_id=1, run_key="r", ref="#a", label="Notice period", kind="text",
                    status="needs_answer", source="qbank_likely", answer="30",
                    retrieval_kind="shortlist", retrieved_qkey="notice_period", retrieval_score=0.62)
    rid = conn.execute("select max(id) from application_qa").fetchone()[0]
    conn.close()
    assert c.post(f"/api/jobs/1/questions/{rid}/reply", json={"answer": "45"}).status_code == 200
    conn = init_db(db)
    row = conn.execute("select source, outcome, status from application_qa where id=?", (rid,)).fetchone()
    conn.close()
    assert row == ("qbank_likely", "edited", "answered")
    bands = {b["band"]: b for b in qa_store.retrieval_stats(init_db(db))["by_band"]}
    assert bands["0.6–0.7"]["edited"] == 1


def test_reply_once_closes_without_touching_bank(env):
    c, db = env
    rid = _open(db)
    n = len(c.get("/api/answers").json()["answers"])
    assert c.get("/api/jobs/1/questions").json()["questions"][0]["asked_in"] == 1
    assert c.post(f"/api/jobs/1/questions/{rid}/reply", json={"answer": "Yes"}).status_code == 200
    assert c.get("/api/jobs/1/questions").json()["questions"] == []
    assert len(c.get("/api/answers").json()["answers"]) == n


def test_reply_new_creates_entry(env):
    c, db = env
    rid = _open(db)
    assert c.post(f"/api/jobs/1/questions/{rid}/reply", json={"answer": "Yes", "save_as": "new"}).status_code == 200
    e = _entry(c, "have_you_used_claude_before")
    assert (e["value"], e["atype"]) == ("Yes", "choice")


def test_reply_wording_attaches_and_validates(env):
    c, db = env
    label = "Do you require a work visa sponsorship now or later?"
    rid = _open(db, label, "select")
    url = f"/api/jobs/1/questions/{rid}/reply"
    assert c.post(url, json={"answer": "Yes", "save_as": "wording"}).status_code == 422
    assert c.post(url, json={"answer": "Yes", "save_as": "bogus"}).status_code == 422
    assert c.post(url, json={"answer": "Yes", "save_as": "wording", "entry_id": "sponsorship_required"}).status_code == 200
    assert label in _entry(c, "sponsorship_required")["wordings"]


def test_review_correct_learns_the_wording_and_bands(env):
    c, db = env
    rid = _filled(db)
    assert c.post(f"/api/application-qa/{rid}/review", json={"verdict": "correct"}).status_code == 200
    assert "How many days is your notice?" in _entry(c, "notice_period")["wordings"]
    stats = c.get("/api/retrieval/stats").json()
    assert stats["reviewed"]["kept"] == 1
    assert stats["by_band"] == [{"band": "0.7–0.8", "kept": 1, "edited": 0, "edit_rate": 0.0}]


def test_review_wrong_repoints_to_the_right_entry(env):
    c, db = env
    rid = _filled(db, label="When does your current job end?")
    assert c.post(f"/api/application-qa/{rid}/review",
                  json={"verdict": "wrong", "entry_id": "last_working_day"}).status_code == 200
    assert "When does your current job end?" in _entry(c, "last_working_day")["wordings"]
    assert "When does your current job end?" not in _entry(c, "notice_period")["wordings"]
    stats = c.get("/api/retrieval/stats").json()
    assert stats["reviewed"]["edited"] == 1 and stats["top_wrong_entries"][0]["qkey"] == "notice_period"


def test_review_validation(env):
    c, db = env
    assert c.post("/api/application-qa/1/review", json={"verdict": "meh"}).status_code == 422
    assert c.post("/api/application-qa/99/review", json={"verdict": "correct"}).status_code == 404
    rid = _filled(db)
    assert c.post(f"/api/application-qa/{rid}/review", json={"verdict": "wrong", "entry_id": "nope"}).status_code == 422


def test_settings_include_qbank_threshold(env):
    c, _ = env
    s = c.get("/api/agent-settings").json()
    assert s["answer_confidence_min"] == 60 and 0 < s["qbank_confident_min"] <= 100
    assert c.put("/api/agent-settings", json={"qbank_confident_min": 85}).status_code == 200
    assert c.get("/api/agent-settings").json()["qbank_confident_min"] == 85
    assert c.put("/api/agent-settings", json={"qbank_confident_min": 101}).status_code == 422


def test_recent_and_empty_stats(env):
    c, db = env
    assert c.get("/api/retrieval/stats").json()["total_fields"] == 0
    _filled(db)
    (r,) = c.get("/api/retrieval/recent").json()["recent"]
    assert (r["label"], r["retrieval_kind"], r["title"]) == ("How many days is your notice?", "shortlist", "ML Eng")


def test_reply_404_and_blank_422(env):
    c, _ = env
    assert c.post("/api/jobs/1/questions/99/reply", json={"answer": "x"}).status_code == 404
    assert c.post("/api/jobs/1/questions/99/reply", json={"answer": " "}).status_code == 422


def test_ingredients_missing_file_is_empty(env):
    c, _ = env
    assert c.get("/api/ingredients").json() == {"units": [], "skills_pool": []}


def _queue_state(db, job_id=1):
    row = init_db(db).execute("SELECT state FROM apply_queue WHERE job_id = ?", (job_id,)).fetchone()
    return row[0] if row else None


def test_answering_the_last_open_question_requeues_a_parked_job(env):
    from job_dashboard.apply import queue as q
    c, db = env
    first, second = _open(db, "Expected CTC?", "text"), _open(db, "Notice period?", "text")
    conn = init_db(db)
    q.enqueue(conn, 1)
    q.mark(conn, 1, "parked", "needs_answers")
    conn.close()
    c.post(f"/api/jobs/1/questions/{first}/reply", json={"answer": "20 LPA"})
    assert _queue_state(db) == "parked"                      # one still open
    r = c.post(f"/api/jobs/1/questions/{second}/reply", json={"answer": "30 days"})
    assert r.json()["requeued"] is True
    assert _queue_state(db) == "queued"
    assert init_db(db).execute("SELECT status FROM jobs WHERE id = 1").fetchone()[0] == "saved"


def test_answering_does_not_queue_a_job_that_was_never_queued(env):
    c, db = env
    rid = _open(db, "Expected CTC?", "text")
    assert c.post(f"/api/jobs/1/questions/{rid}/reply", json={"answer": "20 LPA"}).json()["requeued"] is False
    assert _queue_state(db) is None
