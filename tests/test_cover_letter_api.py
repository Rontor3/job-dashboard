import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from job_dashboard.api.app import create_app
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing


class FakeLetterEngine:
    """Fake letter engine for testing — no TinyFish/Ollama/LaTeX."""

    def __init__(self):
        self.last_detail = None
        self.generated = []

    def research(self, detail):
        self.last_detail = detail
        return {
            "facts": [
                {"text": "Acme's fraud platform cut losses 40%.", "source_url": "https://acme.com/impact"}
            ],
            "queries_used": ["Acme product"],
            "empty": False,
        }

    def draft(self, detail):
        self.last_detail = detail
        return {
            "body": "Dear Hiring Manager,\n\nI was drawn to Acme's fraud platform cutting losses 40%.\n\nSincerely,\n[Your Name]",
            "company_facts_used": [
                {"text": "Acme's fraud platform cut losses 40%.", "source_url": "https://acme.com/impact"}
            ],
            "flags": [],
            "grounding": {"unsupported_company_claims": []},
        }

    def generate(self, job_id, body):
        self.generated.append((job_id, body))
        return {"cover_letter_id": 42, "pdf_url": "/api/cover-letters/42/pdf"}


class FakeLetterEngineTinyFishDown(FakeLetterEngine):
    """TinyFish down -> empty research bundle; draft still 200 w/ general body."""

    def research(self, detail):
        return {"facts": [], "queries_used": [], "empty": True}

    def draft(self, detail):
        return {
            "body": "Dear Hiring Manager,\n\nI am writing to express my genuine interest.\n\nSincerely,\n[Your Name]",
            "company_facts_used": [],
            "flags": ["general_template:empty_research"],
            "grounding": {"unsupported_company_claims": []},
        }


class FakeLetterEngineNoLualatex(FakeLetterEngine):
    def generate(self, job_id, body):
        raise RuntimeError("lualatex not found — install MacTeX")


@pytest.fixture
def client_with_fake_engine(tmp_path):
    """Create a TestClient with a FAKE letter engine."""
    db_path = tmp_path / "t.db"
    conn = init_db(db_path)
    for n, (title, company) in enumerate(
        [("ML Engineer", "Acme"), ("Chef", "Bistro")], 1
    ):
        insert_job(
            conn,
            JobListing(
                source="s",
                title=title,
                company=company,
                job_url=f"https://x.com/{n}",
                description=f"jd {n}",
            ),
        )
    ids = [r[0] for r in conn.execute("SELECT id FROM jobs ORDER BY id").fetchall()]
    conn.close()

    fake_engine = FakeLetterEngine()
    app = create_app(db_path=str(db_path), letter_engine=fake_engine)
    return TestClient(app), ids, fake_engine


def test_research_shape(client_with_fake_engine):
    """POST /api/jobs/{id}/cover-letter/research returns facts/queries_used/empty."""
    tc, ids, _ = client_with_fake_engine
    resp = tc.post(f"/api/jobs/{ids[0]}/cover-letter/research")
    assert resp.status_code == 200
    body = resp.json()
    assert "facts" in body and "queries_used" in body and "empty" in body
    assert isinstance(body["facts"], list)
    assert body["facts"][0]["text"]
    assert body["facts"][0]["source_url"]
    assert body["empty"] is False


def test_research_unknown_job(client_with_fake_engine):
    tc, _, _ = client_with_fake_engine
    resp = tc.post("/api/jobs/999999/cover-letter/research")
    assert resp.status_code == 404


def test_draft_shape(client_with_fake_engine):
    """POST /api/jobs/{id}/cover-letter/draft returns body/company_facts_used/flags/grounding."""
    tc, ids, _ = client_with_fake_engine
    resp = tc.post(f"/api/jobs/{ids[0]}/cover-letter/draft")
    assert resp.status_code == 200
    body = resp.json()
    assert "body" in body and body["body"]
    assert "company_facts_used" in body
    assert isinstance(body["company_facts_used"], list)
    assert "flags" in body
    assert "grounding" in body
    assert "unsupported_company_claims" in body["grounding"]
    assert isinstance(body["grounding"]["unsupported_company_claims"], list)


def test_draft_unknown_job(client_with_fake_engine):
    tc, _, _ = client_with_fake_engine
    resp = tc.post("/api/jobs/999999/cover-letter/draft")
    assert resp.status_code == 404


def test_draft_tinyfish_down_graceful(tmp_path):
    """TinyFish down -> draft still 200 with empty facts, general body."""
    db_path = tmp_path / "t.db"
    conn = init_db(db_path)
    insert_job(
        conn,
        JobListing(source="s", title="ML Engineer", company="Acme",
                   job_url="https://x.com/1", description="jd 1"),
    )
    job_id = conn.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
    conn.close()

    app = create_app(db_path=str(db_path), letter_engine=FakeLetterEngineTinyFishDown())
    tc = TestClient(app)

    resp = tc.post(f"/api/jobs/{job_id}/cover-letter/draft")
    assert resp.status_code == 200
    body = resp.json()
    assert body["company_facts_used"] == []
    assert body["body"]

    research_resp = tc.post(f"/api/jobs/{job_id}/cover-letter/research")
    assert research_resp.status_code == 200
    assert research_resp.json()["facts"] == []
    assert research_resp.json()["empty"] is True


def test_generate_unknown_job(client_with_fake_engine):
    tc, _, _ = client_with_fake_engine
    resp = tc.post("/api/jobs/999999/cover-letter/generate", json={"body": "Dear Hiring Manager,..."})
    assert resp.status_code == 404


def test_generate_lualatex_error(tmp_path):
    """POST /api/jobs/{id}/cover-letter/generate returns 503 if lualatex missing."""
    db_path = tmp_path / "t.db"
    conn = init_db(db_path)
    insert_job(
        conn,
        JobListing(source="s", title="ML Engineer", company="Acme",
                   job_url="https://x.com/1", description="jd 1"),
    )
    job_id = conn.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
    conn.close()

    app = create_app(db_path=str(db_path), letter_engine=FakeLetterEngineNoLualatex())
    tc = TestClient(app)

    resp = tc.post(f"/api/jobs/{job_id}/cover-letter/generate", json={"body": "Dear Hiring Manager,..."})
    assert resp.status_code == 503
    assert "MacTeX" in resp.json()["detail"]


def test_generate_then_list_and_pdf_roundtrip(tmp_path):
    """POST generate persists a cover letter; GET list + GET pdf return it."""
    db_path = tmp_path / "t.db"
    conn = init_db(db_path)
    insert_job(
        conn,
        JobListing(source="s", title="ML Engineer", company="Acme",
                   job_url="https://x.com/1", description="jd 1"),
    )
    job_id = conn.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
    conn.close()

    class PersistingFakeLetterEngine(FakeLetterEngine):
        def generate(self, job_id, body):
            letters_dir = db_path.parent / "cover_letters"
            letters_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = letters_dir / f"cover_letter_{job_id}.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%EOF\n")

            from job_dashboard.db import save_cover_letter

            temp_conn = init_db(db_path)
            cover_letter_id = save_cover_letter(
                temp_conn, job_id, str(pdf_path), body,
                [{"text": "Acme's fraud platform cut losses 40%.", "source_url": "https://acme.com/impact"}],
            )
            temp_conn.close()
            return {
                "cover_letter_id": cover_letter_id,
                "pdf_url": f"/api/cover-letters/{cover_letter_id}/pdf",
            }

    app = create_app(db_path=str(db_path), letter_engine=PersistingFakeLetterEngine())
    tc = TestClient(app)

    gen_resp = tc.post(f"/api/jobs/{job_id}/cover-letter/generate", json={"body": "Dear Hiring Manager,..."})
    assert gen_resp.status_code == 200
    gen_body = gen_resp.json()
    assert "cover_letter_id" in gen_body
    assert "pdf_url" in gen_body
    cover_letter_id = gen_body["cover_letter_id"]

    list_resp = tc.get(f"/api/jobs/{job_id}/cover-letters")
    assert list_resp.status_code == 200
    letters = list_resp.json()["cover_letters"]
    assert len(letters) == 1
    assert letters[0]["id"] == cover_letter_id
    assert letters[0]["body"] == "Dear Hiring Manager,..."

    pdf_resp = tc.get(f"/api/cover-letters/{cover_letter_id}/pdf")
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert b"%PDF" in pdf_resp.content


def test_list_cover_letters_unknown_job(client_with_fake_engine):
    tc, _, _ = client_with_fake_engine
    resp = tc.get("/api/jobs/999999/cover-letters")
    assert resp.status_code == 404


def test_list_cover_letters_empty(client_with_fake_engine):
    tc, ids, _ = client_with_fake_engine
    resp = tc.get(f"/api/jobs/{ids[0]}/cover-letters")
    assert resp.status_code == 200
    assert resp.json()["cover_letters"] == []


def test_get_cover_letter_pdf_unknown(client_with_fake_engine):
    tc, _, _ = client_with_fake_engine
    resp = tc.get("/api/cover-letters/999999/pdf")
    assert resp.status_code == 404
