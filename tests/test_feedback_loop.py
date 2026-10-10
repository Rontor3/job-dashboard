"""Every click teaches the agent: Skip reasons re-rank the feed, Apply rewards similar jobs, the inbox lists what
the agent needs, and the fit-judge prompt carries what was learned."""
import pytest
from fastapi.testclient import TestClient

from job_dashboard import qa_store
from job_dashboard.api.app import create_app
from job_dashboard.db import init_db, insert_job, upsert_embed_score
from job_dashboard.match import deep_rank, preferences
from job_dashboard.models import JobListing

JOBS = [  # (title, company, location, embed score)
    ("Senior Data Analyst", "Acme", "Bengaluru", 0.80),
    ("Machine Learning Engineer", "Beta", "Bengaluru", 0.70),
    ("Data Analyst", "Gamma", "Pune", 0.79),
    ("LLM Engineer", "Delta", "Remote", 0.69),
    ("Machine Learning Engineer", "Spammy Corp", "Bengaluru", 0.95),
]


@pytest.fixture
def env(tmp_path, fake_embed):
    db = str(tmp_path / "t.db")
    c = init_db(db)
    for i, (title, company, loc, score) in enumerate(JOBS, 1):
        insert_job(c, JobListing(source="s", title=title, company=company, location=loc,
                                 job_url=f"https://x/{i}", description="jd"))
        upsert_embed_score(c, i, score, "h")
    c.close()
    return TestClient(create_app(db_path=db, qa_embed=fake_embed, queue_launch=lambda *a: 0)), db


def _feed(c):
    return [(j["title"], j["company"]) for j in c.get("/api/jobs?sort=learned").json()["jobs"]]


def test_skipping_a_role_pushes_similar_roles_down(env):
    c, _ = env
    assert _feed(c)[1] == ("Senior Data Analyst", "Acme")
    c.post("/api/jobs/1/feedback", json={"verdict": "skip", "reasons": ["role"]})
    feed = _feed(c)
    assert ("Senior Data Analyst", "Acme") not in feed            # the skipped job is gone
    assert feed.index(("Data Analyst", "Gamma")) > feed.index(("LLM Engineer", "Delta"))


def test_a_company_skip_hides_every_job_from_that_company(env):
    c, _ = env
    c.post("/api/jobs/5/feedback", json={"verdict": "skip", "reasons": ["company"]})
    assert all(company != "Spammy Corp" for _, company in _feed(c))
    assert c.get("/api/preferences").json()["blocked_companies"] == ["spammy corp"]


def test_a_location_skip_never_penalises_the_title(env):
    c, db = env
    c.post("/api/jobs/3/feedback", json={"verdict": "skip", "reasons": ["location"]})
    learned = preferences.learn(init_db(db))
    assert learned["weights"].get("loc:pune") == -1
    assert not any(k.startswith("title:") for k in learned["weights"])


def test_queueing_a_job_teaches_more_like_this(env):
    c, _ = env
    c.post("/api/queue", json={"job_id": 4})
    likes = [x["label"] for x in c.get("/api/preferences").json()["likes"]]
    assert "llm" in likes and "engineer" in likes


def test_forgetting_a_preference_undoes_its_effect(env):
    c, _ = env
    c.post("/api/jobs/1/feedback", json={"verdict": "skip", "reasons": ["role"]})
    c.delete("/api/preferences/title:analyst")
    assert "analyst" not in [x["label"] for x in c.get("/api/preferences").json()["dislikes"]]


def test_unknown_reason_is_rejected(env):
    c, _ = env
    assert c.post("/api/jobs/1/feedback", json={"verdict": "skip", "reasons": ["vibes"]}).status_code == 422


def test_fit_judge_prompt_carries_learned_preferences(env):
    c, db = env
    c.post("/api/jobs/1/feedback", json={"verdict": "skip", "reasons": ["role"]})
    prompts = []
    deep_rank.deep_rank_unranked(init_db(db), llm=lambda p: prompts.append(p) or "Verdict: Good Fit\nScore: 70",
                                 profile_text="ML engineer", candidate_years=3)
    assert prompts and all("has repeatedly skipped" in p and "analyst" in p for p in prompts)


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


def test_explain_asks_the_model_about_the_question_and_its_choices(env, monkeypatch):
    c, _ = env
    seen = []
    monkeypatch.setattr("job_dashboard.llm.complete", lambda prompt, **kw: seen.append(prompt) or " They ask whether you agree. ")
    r = c.post("/api/explain", json={"question": "Do you acknowledge our AI policy?", "options": ["Yes", "No"]})
    assert r.json() == {"explanation": "They ask whether you agree."}
    assert "Do you acknowledge our AI policy?" in seen[0] and "Yes, No" in seen[0]


def test_explain_reports_an_unreachable_model_instead_of_failing_silently(env, monkeypatch):
    c, _ = env
    def down(*a, **k):
        raise ConnectionError("refused")
    monkeypatch.setattr("job_dashboard.llm.complete", down)
    assert c.post("/api/explain", json={"question": "Q?"}).status_code == 503
