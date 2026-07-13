import pytest
from fastapi.testclient import TestClient

from job_dashboard.api.app import create_app
from job_dashboard.db import (
    init_db, insert_job, mark_duplicate, record_llm_evaluation, upsert_embed_score,
)
from job_dashboard.models import JobListing


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "t.db"
    conn = init_db(db_path)
    for n, (title, company) in enumerate(
        [("ML Engineer", "Stripe"), ("Chef", "Bistro"), ("AI Engineer", "Acme")], 1
    ):
        insert_job(conn, JobListing(source="s", title=title, company=company,
                                    job_url=f"https://x.com/{n}", description=f"jd {n}"))
    ids = [r[0] for r in conn.execute("SELECT id FROM jobs ORDER BY id").fetchall()]
    upsert_embed_score(conn, ids[0], 0.9, "h")
    record_llm_evaluation(conn, ids[0], 87, "Strong Fit", ["prod ML"], ["k8s"], {})
    mark_duplicate(conn, ids[2], ids[0])
    conn.close()
    app = create_app(db_path=str(db_path))
    return TestClient(app), ids


def test_get_jobs_returns_canonical_scored_feed(client):
    tc, ids = client
    resp = tc.get("/api/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2  # duplicate excluded
    assert body["jobs"][0]["id"] == ids[0]
    assert body["jobs"][0]["llm_score"] == 87


def test_get_jobs_filters_pass_through(client):
    tc, _ = client
    assert tc.get("/api/jobs", params={"q": "stripe"}).json()["total"] == 1
    assert tc.get("/api/jobs", params={"min_score": 0.5}).json()["total"] == 1


def test_job_detail_and_404(client):
    tc, ids = client
    body = tc.get(f"/api/jobs/{ids[0]}").json()
    assert body["description"] == "jd 1"
    assert body["strengths"] == ["prod ML"]
    assert body["cross_listings"][0]["id"] == ids[2]
    assert tc.get("/api/jobs/999999").status_code == 404


def test_patch_status_validates(client):
    tc, ids = client
    assert tc.patch(f"/api/jobs/{ids[1]}/status", json={"status": "saved"}).status_code == 200
    assert tc.get(f"/api/jobs/{ids[1]}").json()["status"] == "saved"
    assert tc.patch(f"/api/jobs/{ids[1]}/status", json={"status": None}).status_code == 200
    assert tc.patch(f"/api/jobs/{ids[1]}/status", json={"status": "bogus"}).status_code == 422
    assert tc.patch("/api/jobs/999999/status", json={"status": "saved"}).status_code == 404


def test_duplicates_and_stats(client):
    tc, ids = client
    dupes = tc.get("/api/duplicates").json()["duplicates"]
    assert len(dupes) == 1 and dupes[0]["duplicate_of"] == ids[0]

    stats = tc.get("/api/stats").json()
    assert stats["total"] == 2 and stats["unranked"] == 1
