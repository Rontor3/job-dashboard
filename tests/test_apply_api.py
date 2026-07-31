from fastapi.testclient import TestClient
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing
from job_dashboard.api.app import create_app


def _client(tmp_path):
    db = str(tmp_path / "t.db")
    c = init_db(db)
    insert_job(c, JobListing(source="s", title="ML Eng", company="Acme",
                             job_url="https://boards.greenhouse.io/acme/jobs/1", description="jd"))
    jid = c.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
    c.close()

    class FakeScreening:
        def answer(self, detail, question):
            return {"answer": f"Because {detail.get('company')} is great.", "flags": []}
    return TestClient(create_app(db_path=db, screening_engine=FakeScreening())), jid


def test_profile_put_then_get(tmp_path):
    c, _ = _client(tmp_path)
    r = c.put("/api/application-profile", json={"full_name": "R", "email": "r@x.com"})
    assert r.status_code == 200 and r.json()["full_name"] == "R"
    assert c.get("/api/application-profile").json()["email"] == "r@x.com"


def test_package_has_optional_cover_letter_and_ats_hint(tmp_path):
    c, jid = _client(tmp_path)
    r = c.get(f"/api/jobs/{jid}/application-package")
    assert r.status_code == 200
    body = r.json()
    assert body["cover_letter"] is None and body["ats_hint"] == "greenhouse"


def test_screening_answer_shape(tmp_path):
    c, jid = _client(tmp_path)
    r = c.post(f"/api/jobs/{jid}/screening-answer", json={"question": "Why us?"})
    assert r.status_code == 200 and "answer" in r.json()


def test_application_create_then_get_roundtrip(tmp_path):
    c, jid = _client(tmp_path)
    r = c.post(f"/api/jobs/{jid}/application",
               json={"resume_id": None, "cover_letter_id": None,
                     "screening": [{"question": "Q", "answer": "A"}],
                     "ats": "greenhouse", "status": "applied"})
    assert r.status_code == 200
    got = c.get(f"/api/jobs/{jid}/application").json()
    assert got["status"] == "applied" and got["cover_letter_id"] is None


def test_ats_map_route_and_404s(tmp_path):
    c, _ = _client(tmp_path)
    assert c.get("/api/ats-map/greenhouse").status_code == 200
    assert c.get("/api/ats-map/nosuch").status_code == 404
    assert c.get("/api/jobs/99999/application-package").status_code == 404
