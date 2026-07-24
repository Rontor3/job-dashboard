import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from job_dashboard.api.app import create_app
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing
from job_dashboard.resume.keyword_map import Rephrasing


class FakeResumeEngine:
    """Fake resume engine for testing — no LaTeX/LLM."""

    def __init__(self):
        self.last_job_id = None

    def suggest_blocks(self, jd_text, job_id):
        """Return fake suggestion without running LLM."""
        self.last_job_id = job_id
        return {
            "block_ids": ["header", "summary", "exp1"],
            "rationale": {"header": 0.9, "summary": 0.8, "exp1": 0.7},
            "rephrasings": [
                Rephrasing(
                    block_id="exp1",
                    original_text="Built systems",
                    proposed_text="Built ML systems",
                    jd_keyword="machine learning",
                    confidence="transferable",
                    needs_interview_prep=True,
                )
            ],
            "gaps": [],
        }

    def generate_resume(self, job_id, block_ids, accepted_rephrasings):
        """Return fake resume without rendering LaTeX."""
        return {
            "resume_id": 42,
            "pdf_url": "/api/resumes/42/pdf",
            "ats_report": {
                "ats_score": 85,
                "contact_ok": True,
                "reading_order_ok": True,
                "keyword_coverage": 0.9,
                "missing_keywords": [],
                "warnings": [],
            },
            "blocks_used": block_ids,
            "cut_lines": [],
            "interview_prep": [
                {
                    "block_id": "exp1",
                    "jd_keyword": "machine learning",
                    "proposed_text": "Built ML systems",
                }
            ],
        }


@pytest.fixture
def client_with_fake_engine(tmp_path):
    """Create a TestClient with a FAKE resume engine."""
    db_path = tmp_path / "t.db"
    conn = init_db(db_path)
    for n, (title, company) in enumerate(
        [("ML Engineer", "Stripe"), ("Chef", "Bistro"), ("AI Engineer", "Acme")], 1
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

    fake_engine = FakeResumeEngine()
    app = create_app(db_path=str(db_path), resume_engine=fake_engine)
    return TestClient(app), ids, fake_engine


def test_get_segments(client_with_fake_engine):
    """GET /api/resume/segments returns block manifest."""
    tc, _, _ = client_with_fake_engine
    resp = tc.get("/api/resume/segments")
    assert resp.status_code == 200
    body = resp.json()
    assert "segments" in body
    assert isinstance(body["segments"], list)
    if body["segments"]:
        seg = body["segments"][0]
        assert "id" in seg
        assert "kind" in seg
        assert "title" in seg
        assert "tags" in seg
        assert "exclusive_group" in seg


def test_suggest_blocks_success(client_with_fake_engine):
    """POST /api/jobs/{id}/resume/suggest returns suggestions."""
    tc, ids, _ = client_with_fake_engine
    resp = tc.post(f"/api/jobs/{ids[0]}/resume/suggest")
    assert resp.status_code == 200
    body = resp.json()
    assert "block_ids" in body
    assert "rationale" in body
    assert "rephrasings" in body
    assert "gaps" in body
    assert isinstance(body["block_ids"], list)
    assert isinstance(body["rationale"], dict)
    assert isinstance(body["rephrasings"], list)
    assert isinstance(body["gaps"], list)


def test_suggest_blocks_unknown_job(client_with_fake_engine):
    """POST /api/jobs/{id}/resume/suggest returns 404 for unknown job."""
    tc, _, _ = client_with_fake_engine
    resp = tc.post("/api/jobs/999999/resume/suggest")
    assert resp.status_code == 404


def test_generate_resume_success(client_with_fake_engine):
    """POST /api/jobs/{id}/resume/generate returns resume_id + metadata."""
    tc, ids, _ = client_with_fake_engine
    # First suggest
    suggest_resp = tc.post(f"/api/jobs/{ids[0]}/resume/suggest")
    suggest_body = suggest_resp.json()
    block_ids = suggest_body["block_ids"]

    # Generate
    body = {
        "block_ids": block_ids,
        "accepted_rephrasings": [
            {
                "block_id": "exp1",
                "original_text": "Built systems",
                "proposed_text": "Built ML systems",
                "jd_keyword": "machine learning",
                "confidence": "transferable",
                "needs_interview_prep": True,
            }
        ],
    }
    resp = tc.post(f"/api/jobs/{ids[0]}/resume/generate", json=body)
    assert resp.status_code == 200
    result = resp.json()
    assert "resume_id" in result
    assert "pdf_url" in result
    assert "ats_report" in result
    assert "blocks_used" in result
    assert "cut_lines" in result
    assert "interview_prep" in result

    # ats_report should have expected fields
    ats = result["ats_report"]
    assert "ats_score" in ats
    assert "contact_ok" in ats
    assert "reading_order_ok" in ats
    assert "keyword_coverage" in ats
    assert "missing_keywords" in ats
    assert "warnings" in ats


def test_generate_resume_unknown_job(client_with_fake_engine):
    """POST /api/jobs/{id}/resume/generate returns 404 for unknown job."""
    tc, _, _ = client_with_fake_engine
    body = {"block_ids": ["header"], "accepted_rephrasings": []}
    resp = tc.post("/api/jobs/999999/resume/generate", json=body)
    assert resp.status_code == 404


def test_generate_resume_lualatex_error():
    """POST /api/jobs/{id}/resume/generate returns 503 if lualatex missing."""
    import tempfile

    class FakeEngineWithLaTeXError(FakeResumeEngine):
        def generate_resume(self, job_id, block_ids, accepted_rephrasings):
            raise RuntimeError("lualatex not found — install MacTeX")

    with tempfile.TemporaryDirectory() as tmp_path:
        tmp_path = Path(tmp_path)
        db_path = tmp_path / "t.db"
        conn = init_db(db_path)
        insert_job(
            conn,
            JobListing(
                source="s",
                title="Test",
                company="Test",
                job_url="https://x.com/1",
                description="jd 1",
            ),
        )
        job_id = conn.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
        conn.close()

        fake_engine = FakeEngineWithLaTeXError()
        app = create_app(db_path=str(db_path), resume_engine=fake_engine)
        tc = TestClient(app)

        body = {"block_ids": ["header"], "accepted_rephrasings": []}
        resp = tc.post(f"/api/jobs/{job_id}/resume/generate", json=body)
        assert resp.status_code == 503
        assert "MacTeX" in resp.json()["detail"]


def test_list_job_resumes(client_with_fake_engine):
    """GET /api/jobs/{id}/resumes returns list of resumes."""
    tc, ids, _ = client_with_fake_engine
    resp = tc.get(f"/api/jobs/{ids[0]}/resumes")
    assert resp.status_code == 200
    body = resp.json()
    assert "resumes" in body
    assert isinstance(body["resumes"], list)


def test_list_job_resumes_unknown_job(client_with_fake_engine):
    """GET /api/jobs/{id}/resumes returns 404 for unknown job."""
    tc, _, _ = client_with_fake_engine
    resp = tc.get("/api/jobs/999999/resumes")
    assert resp.status_code == 404


def test_get_resume_pdf_unknown_resume(client_with_fake_engine):
    """GET /api/resumes/{id}/pdf returns 404 for unknown resume."""
    tc, _, _ = client_with_fake_engine
    resp = tc.get("/api/resumes/999999/pdf")
    assert resp.status_code == 404


def test_generate_and_fetch_resume_pdf(tmp_path):
    """Full flow: generate resume and fetch PDF."""
    db_path = tmp_path / "t.db"
    conn = init_db(db_path)
    insert_job(
        conn,
        JobListing(
            source="s",
            title="ML Engineer",
            company="Stripe",
            job_url="https://x.com/1",
            description="jd 1",
        ),
    )
    job_id = conn.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]

    # Create a fake PDF file in the resumes directory
    resumes_dir = db_path.parent / "resumes"
    resumes_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = resumes_dir / "resume_1.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%EOF\n")  # Minimal valid PDF

    # Manually save a resume to the database
    from job_dashboard.db import save_resume

    resume_id = save_resume(
        conn,
        job_id,
        str(pdf_path),
        ["header", "summary"],
        85,
        {
            "ats_score": 85,
            "contact_ok": True,
            "reading_order_ok": True,
            "keyword_coverage": 0.9,
            "missing_keywords": [],
            "warnings": [],
        },
    )
    conn.close()

    app = create_app(db_path=str(db_path))
    tc = TestClient(app)

    # Fetch the PDF
    resp = tc.get(f"/api/resumes/{resume_id}/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert b"%PDF" in resp.content
