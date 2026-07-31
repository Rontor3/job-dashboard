from fastapi.testclient import TestClient

from job_dashboard.api.app import create_app
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing  # the dataclass insert_job expects


def _seed_job(db):
    conn = init_db(db)
    insert_job(conn, JobListing(source="s", title="Data Scientist", company="Acme",
                                job_url="https://x.com/1", description="fraud ML role"))
    jid = conn.execute("SELECT id FROM jobs ORDER BY id LIMIT 1").fetchone()[0]
    conn.close()
    return jid


class FakeEngine:
    def __init__(self, db_path):
        self.db_path = db_path

    def gather_resources(self, detail):
        return {"company": detail.get("company"), "resources": [
            {"source_url": "https://acme.com/acs", "title": "acme.com",
             "summary": "Account Confidence Score, an AI/ML fraud score.", "selected": False},
            {"source_url": "https://blog.acme.com/mesh", "title": "blog.acme.com",
             "summary": "Built a data mesh.", "selected": False},
        ]}

    def list_resources(self, detail):
        return {"company": detail.get("company"), "resources": []}

    def select_resources(self, detail, source_urls):
        return {"company": detail.get("company"),
                "resources": [{"source_url": u, "title": "t", "summary": "s",
                               "selected": True} for u in source_urls[:2]]}

    def draft(self, detail):
        return {"body": "Dear Hiring Manager, ...", "company_facts_used": [],
                "flags": [], "grounding": {"unsupported_company_claims": []}}

    def generate(self, job_id, body):
        return {"cover_letter_id": 1, "pdf_url": "/api/cover-letters/1/pdf"}


def test_gather_list_select_flow(tmp_path):
    db = str(tmp_path / "t.db")
    jid = _seed_job(db)
    c = TestClient(create_app(db_path=db, letter_engine=FakeEngine(db)))
    r = c.post(f"/api/jobs/{jid}/company-research")
    assert r.status_code == 200
    assert len(r.json()["resources"]) == 2
    r = c.post(f"/api/jobs/{jid}/company-resources/select",
               json={"source_urls": ["https://acme.com/acs"]})
    assert r.status_code == 200
    assert r.json()["resources"][0]["selected"] is True
    assert c.get(f"/api/jobs/{jid}/company-resources").status_code == 200


def test_unknown_job_404(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db)
    c = TestClient(create_app(db_path=db, letter_engine=FakeEngine(db)))
    assert c.post("/api/jobs/999999/company-research").status_code == 404
    assert c.post("/api/jobs/999999/company-resources/select",
                  json={"source_urls": []}).status_code == 404
