"""Every click teaches the Jobs ranking: Skip reasons re-rank it, Apply/Queue rewards similar jobs."""
import pytest
from fastapi.testclient import TestClient

from job_dashboard.api.app import create_app
from job_dashboard.db import init_db, insert_job, upsert_embed_score
from job_dashboard.match import preferences
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


def test_batch_queue_skips_applied_jobs_and_reports_them(env):
    c, db = env
    conn = init_db(db)
    conn.execute("UPDATE jobs SET status = 'applied' WHERE id = 2")
    conn.commit()
    r = c.post("/api/queue/batch", json={"job_ids": [1, 2, 3, 1]}).json()
    assert r["queued"] == [1, 3]
    assert r["skipped"] == [{"job_id": 2, "why": "applied"}]
    assert [i["job_id"] for i in r["items"]] == [1, 3]


def test_ids_limits_the_feed_to_that_set(env):
    c, _ = env
    assert {j["id"] for j in c.get("/api/jobs?sort=learned&ids=2,4").json()["jobs"]} == {2, 4}
