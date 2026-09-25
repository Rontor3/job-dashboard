import pytest
from fastapi.testclient import TestClient

from job_dashboard import qa_store
from job_dashboard.api.app import create_app
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing


class FakeVault:
    def __init__(self):
        self.d = {}

    def list_all(self):
        return [{"question": q, **m} for q, m in self.d.items()]

    def delete(self, question):
        self.d.pop(question, None)

    def record_feedback(self, question, answer, event):
        self.d[question] = {"answer": answer, "confidence": 0.0, "approved_count": 0}
        return self.d[question]


class BrokenVault(FakeVault):
    def list_all(self):
        raise RuntimeError("chroma down")


@pytest.fixture
def env(tmp_path):
    db = str(tmp_path / "t.db")
    c = init_db(db)
    insert_job(c, JobListing(source="s", title="ML Eng", company="Acme",
                             job_url="https://x/1", description="jd"))
    c.close()
    vault = FakeVault()
    return TestClient(create_app(db_path=db, qa_vault=vault)), vault, db


def _learned(db):
    c = init_db(db)
    rows = c.execute("select qkey, answer from learned_answers").fetchall()
    c.close()
    return dict(rows)


def test_short_answer_is_written_to_both_stores_and_listed_merged(env):
    c, vault, db = env
    assert c.put("/api/answers", json={"question": "Notice period?", "answer": "30 days"}).status_code == 200
    assert _learned(db) == {"notice period": "30 days"} and "Notice period?" in vault.d
    (a,) = c.get("/api/answers").json()["answers"]
    assert (a["qkey"], a["answer"], a["in_learned"], a["in_vault"]) == ("notice period", "30 days", True, True)
    assert c.get("/api/answers?q=zzz").json()["answers"] == []


def test_essay_goes_to_vault_only(env):
    c, vault, db = env
    c.put("/api/answers", json={"question": "Why us?", "answer": "x" * 300})
    assert _learned(db) == {} and "Why us?" in vault.d


def test_delete_removes_both_and_404s_when_absent(env):
    c, vault, db = env
    c.put("/api/answers", json={"question": "Notice period?", "answer": "30 days"})
    r = c.delete("/api/answers", params={"qkey": "notice period"})
    assert r.json()["removed"] == {"learned": True, "vault": True}
    assert _learned(db) == {} and vault.d == {}
    assert c.delete("/api/answers", params={"qkey": "notice period"}).status_code == 404


def test_reply_teaches_memory_and_closes_question(env):
    c, vault, db = env
    conn = init_db(db)
    qa_store.record(conn, job_id=1, run_key="r", ref="#a", label="Notice period?",
                    kind="text", status="needs_answer")
    rid = conn.execute("select id from application_qa").fetchone()[0]
    conn.close()
    assert c.get("/api/questions/open-counts").json() == {"1": 1}
    assert len(c.get("/api/jobs/1/questions").json()["questions"]) == 1
    assert c.post(f"/api/jobs/1/questions/{rid}/reply", json={"answer": "30 days"}).status_code == 200
    assert _learned(db) == {"notice period": "30 days"}
    assert c.get("/api/jobs/1/questions").json()["questions"] == []
    assert c.get("/api/questions/open-counts").json() == {}
    assert c.get("/api/answers").json()["answers"][0]["asked_in"] == 1


def test_textarea_reply_is_vault_only(env):
    c, vault, db = env
    conn = init_db(db)
    qa_store.record(conn, job_id=1, run_key="r", ref="#e", label="Why us?", kind="textarea",
                    status="needs_answer")
    rid = conn.execute("select id from application_qa").fetchone()[0]
    conn.close()
    c.post(f"/api/jobs/1/questions/{rid}/reply", json={"answer": "short essay"})
    assert _learned(db) == {} and "Why us?" in vault.d


def test_reply_404_and_blank_422(env):
    c, _, _ = env
    assert c.post("/api/jobs/1/questions/99/reply", json={"answer": "x"}).status_code == 404
    assert c.post("/api/jobs/1/questions/99/reply", json={"answer": " "}).status_code == 422


def test_settings_default_update_and_bounds(env):
    c, _, _ = env
    assert c.get("/api/agent-settings").json() == {"answer_confidence_min": 60}
    assert c.put("/api/agent-settings", json={"answer_confidence_min": 75}).status_code == 200
    assert c.get("/api/agent-settings").json()["answer_confidence_min"] == 75
    assert c.put("/api/agent-settings", json={"answer_confidence_min": 101}).status_code == 422


def test_vault_down_still_lists_learned_answers(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    from career_agent.memory.learned_answers import ensure
    ensure(conn)
    conn.execute("insert into learned_answers (qkey,label,answer,purpose,updated_at) values "
                 "('q','Q?','A',null,'2026-01-01')")
    conn.commit(); conn.close()
    c = TestClient(create_app(db_path=db, qa_vault=BrokenVault()))
    assert c.get("/api/answers").json()["answers"][0]["answer"] == "A"


def test_ingredients_missing_file_is_empty(env):
    c, _, _ = env
    assert c.get("/api/ingredients").json() == {"units": [], "skills_pool": []}


def _seed_filled(db, **kw):
    conn = init_db(db)
    qa_store.record(conn, job_id=1, run_key="r", ref="#a", label="Years of Python?", kind="text",
                    status="filled", answer="2", source="learned", retrieval_kind="fts_fuzzy",
                    retrieved_qkey="years of java", retrieval_score=0.6, **kw)
    rid = conn.execute("select id from application_qa").fetchone()[0]
    conn.close()
    return rid


def test_review_wrong_with_fix_teaches_memory_and_marks_edited(env):
    c, vault, db = env
    rid = _seed_filled(db)
    (used,) = c.get("/api/jobs/1/answers-used").json()["answers"]
    assert used["retrieved_qkey"] == "years of java" and used["outcome"] is None
    assert c.post(f"/api/application-qa/{rid}/review", json={"verdict": "wrong", "answer": "4"}).status_code == 200
    assert _learned(db) == {"years of python": "4"}          # the right answer is now in memory
    assert c.get("/api/jobs/1/answers-used").json()["answers"][0]["outcome"] == "edited"
    stats = c.get("/api/retrieval/stats").json()
    assert stats["reviewed"] == {"kept": 0, "edited": 1, "wrong_rate": 1.0}
    assert stats["top_wrong_entries"][0]["qkey"] == "years of java"


def test_review_correct_marks_kept_without_touching_memory(env):
    c, vault, db = env
    rid = _seed_filled(db)
    assert c.post(f"/api/application-qa/{rid}/review", json={"verdict": "correct"}).status_code == 200
    assert _learned(db) == {} and vault.d == {}
    assert c.get("/api/retrieval/stats").json()["reviewed"]["kept"] == 1


def test_review_validation(env):
    c, _, _ = env
    assert c.post("/api/application-qa/1/review", json={"verdict": "meh"}).status_code == 422
    assert c.post("/api/application-qa/99/review", json={"verdict": "correct"}).status_code == 404


def test_recent_and_empty_stats(env):
    c, _, db = env
    assert c.get("/api/retrieval/stats").json()["total_fields"] == 0
    _seed_filled(db)
    (r,) = c.get("/api/retrieval/recent").json()["recent"]
    assert (r["label"], r["retrieval_kind"], r["title"]) == ("Years of Python?", "fts_fuzzy", "ML Eng")
