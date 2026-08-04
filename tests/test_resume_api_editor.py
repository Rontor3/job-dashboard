"""Task 4: résumé block-editor API — regenerate-block + layout-aware
generate.

Follows the same ``create_app`` + fake-engine pattern as
``tests/test_resume_api.py``. The regenerate-block route is exercised two
ways: monkeypatching ``resume_routes.regenerate_block``/``compose_profile_
text`` (the ``resume_engine=None`` default wiring) and an injected fake
engine (mirrors ``suggest``/``generate``'s existing ``resume_engine``
branch). The layout-aware generate route is exercised by monkeypatching
``resume_routes.generate_resume`` to capture the kwargs it's called with —
``engine.generate_resume``'s own layout COMPOSITION logic already has
dedicated coverage in ``tests/test_generate_layout.py``; this file only
proves the API wires ``body.layout`` through.
"""

import pytest
from fastapi.testclient import TestClient

import job_dashboard.api.resume_routes as resume_routes
from job_dashboard.api.app import create_app
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing


def _seed_job(db_path):
    conn = init_db(db_path)
    insert_job(
        conn,
        JobListing(
            source="s",
            title="ML Engineer",
            company="Stripe",
            job_url="https://x.com/1",
            description="Need a Python engineer with Kubernetes experience.",
        ),
    )
    job_id = conn.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
    conn.close()
    return job_id


# ---------------------------------------------------------------------------
# regenerate-block
# ---------------------------------------------------------------------------


def test_regenerate_block_returns_alternatives(tmp_path, monkeypatch):
    """resume_engine=None default wiring: the route calls resume_llm.
    regenerate_block with (kind, title, bullets, jd_text, profile_text) and
    returns its alternatives verbatim under {"alternatives": [...]}."""
    db_path = tmp_path / "t.db"
    job_id = _seed_job(db_path)

    captured = {}

    def fake_regenerate_block(kind, title, bullets, jd_text, profile_text):
        captured["kind"] = kind
        captured["title"] = title
        captured["bullets"] = bullets
        captured["jd_text"] = jd_text
        captured["profile_text"] = profile_text
        return [["Built **fraud** ML systems"], ["Shipped real-time scoring"]]

    monkeypatch.setattr(resume_routes, "regenerate_block", fake_regenerate_block)
    monkeypatch.setattr(
        resume_routes, "compose_profile_text",
        lambda: type("PT", (), {"text": "candidate profile facts"})(),
    )

    app = create_app(db_path=str(db_path))
    tc = TestClient(app)

    body = {"kind": "experience", "title": "DS", "bullets": ["Built fraud models"]}
    resp = tc.post(f"/api/jobs/{job_id}/resume/regenerate-block", json=body)

    assert resp.status_code == 200
    result = resp.json()
    assert result == {
        "alternatives": [["Built **fraud** ML systems"], ["Shipped real-time scoring"]]
    }

    assert captured["kind"] == "experience"
    assert captured["title"] == "DS"
    assert captured["bullets"] == ["Built fraud models"]
    assert captured["jd_text"] == "Need a Python engineer with Kubernetes experience."
    assert captured["profile_text"] == "candidate profile facts"


def test_regenerate_block_unknown_job(tmp_path):
    """POST regenerate-block returns 404 for unknown job."""
    db_path = tmp_path / "t.db"
    init_db(db_path).close()

    app = create_app(db_path=str(db_path))
    tc = TestClient(app)

    body = {"kind": "experience", "title": "DS", "bullets": ["x"]}
    resp = tc.post("/api/jobs/999999/resume/regenerate-block", json=body)
    assert resp.status_code == 404


def test_regenerate_block_never_500s_when_llm_returns_empty(tmp_path, monkeypatch):
    """regenerate_block returning [] (its own graceful Ollama-down shape,
    see resume_llm.regenerate_block's never-raise contract) must surface
    as a normal 200 with an empty alternatives list, never a 500."""
    db_path = tmp_path / "t.db"
    job_id = _seed_job(db_path)

    monkeypatch.setattr(
        resume_routes, "regenerate_block",
        lambda kind, title, bullets, jd_text, profile_text: [],
    )
    monkeypatch.setattr(
        resume_routes, "compose_profile_text",
        lambda: type("PT", (), {"text": ""})(),
    )

    app = create_app(db_path=str(db_path))
    tc = TestClient(app)

    body = {"kind": "experience", "title": "DS", "bullets": ["x"]}
    resp = tc.post(f"/api/jobs/{job_id}/resume/regenerate-block", json=body)
    assert resp.status_code == 200
    assert resp.json() == {"alternatives": []}


def test_regenerate_block_missing_profile_file_falls_back_gracefully(tmp_path, monkeypatch):
    """compose_profile_text() raising (missing/empty candidate profile
    file — same seam as letter_routes/apply_routes) must not 500; the
    route degrades to an empty profile_text string."""
    db_path = tmp_path / "t.db"
    job_id = _seed_job(db_path)

    captured = {}

    def fake_regenerate_block(kind, title, bullets, jd_text, profile_text):
        captured["profile_text"] = profile_text
        return []

    def boom():
        raise FileNotFoundError("no profile")

    monkeypatch.setattr(resume_routes, "regenerate_block", fake_regenerate_block)
    monkeypatch.setattr(resume_routes, "compose_profile_text", boom)

    app = create_app(db_path=str(db_path))
    tc = TestClient(app)

    body = {"kind": "experience", "title": "DS", "bullets": ["x"]}
    resp = tc.post(f"/api/jobs/{job_id}/resume/regenerate-block", json=body)
    assert resp.status_code == 200
    assert captured["profile_text"] == ""


def test_regenerate_block_via_injected_engine(tmp_path):
    """resume_engine given (injected-engine pattern, mirrors suggest/
    generate's existing branch): the route delegates to resume_engine.
    regenerate_block instead of calling resume_llm.regenerate_block."""

    class FakeResumeEngine:
        def __init__(self):
            self.last_call = None

        def regenerate_block(self, job_id, kind, title, bullets):
            self.last_call = (job_id, kind, title, bullets)
            return [["engine alt one"]]

    db_path = tmp_path / "t.db"
    job_id = _seed_job(db_path)

    fake_engine = FakeResumeEngine()
    app = create_app(db_path=str(db_path), resume_engine=fake_engine)
    tc = TestClient(app)

    body = {"kind": "skills", "title": "Skills", "bullets": ["Python", "SQL"]}
    resp = tc.post(f"/api/jobs/{job_id}/resume/regenerate-block", json=body)

    assert resp.status_code == 200
    assert resp.json() == {"alternatives": [["engine alt one"]]}
    assert fake_engine.last_call == (job_id, "skills", "Skills", ["Python", "SQL"])


# ---------------------------------------------------------------------------
# generate with layout
# ---------------------------------------------------------------------------


def test_generate_with_layout_passes_through_to_engine(tmp_path, monkeypatch):
    """When `layout` is present in the request body, the route must call
    engine.generate_resume(..., layout=layout) — the engine's own layout
    COMPOSITION logic is covered separately in test_generate_layout.py."""
    db_path = tmp_path / "t.db"
    job_id = _seed_job(db_path)

    captured = {}

    def fake_generate_resume(conn, jid, block_ids, accepted_rephrasings, **kwargs):
        captured["job_id"] = jid
        captured["block_ids"] = block_ids
        captured["layout"] = kwargs.get("layout")
        return {
            "resume_id": 7,
            "pdf_path": str(tmp_path / "resume.pdf"),
            "ats_report": {
                "ats_score": 90, "contact_ok": True, "reading_order_ok": True,
                "keyword_coverage": 1.0, "missing_keywords": [], "warnings": [],
            },
            "blocks_used": ["header-contact", "skills-a", "custom-1"],
            "cut_lines": [],
            "interview_prep": [],
        }

    monkeypatch.setattr(resume_routes, "generate_resume", fake_generate_resume)

    app = create_app(db_path=str(db_path))
    tc = TestClient(app)

    layout = [
        {"segment_id": "skills-a"},
        {"kind": "project", "title": "Rocket", "bullets": ["did x"]},
    ]
    body = {"block_ids": [], "accepted_rephrasings": [], "layout": layout}
    resp = tc.post(f"/api/jobs/{job_id}/resume/generate", json=body)

    assert resp.status_code == 200
    result = resp.json()
    assert result["resume_id"] == 7
    assert result["blocks_used"] == ["header-contact", "skills-a", "custom-1"]

    assert captured["job_id"] == job_id
    assert captured["layout"] == layout


def test_generate_without_layout_still_works(tmp_path, monkeypatch):
    """Backward-compat: omitting `layout` from the request body must keep
    the existing block_ids/accepted_rephrasings path working, calling
    generate_resume with layout=None."""
    db_path = tmp_path / "t.db"
    job_id = _seed_job(db_path)

    captured = {}

    def fake_generate_resume(conn, jid, block_ids, accepted_rephrasings, **kwargs):
        captured["block_ids"] = block_ids
        captured["layout"] = kwargs.get("layout")
        return {
            "resume_id": 8,
            "pdf_path": str(tmp_path / "resume.pdf"),
            "ats_report": {
                "ats_score": 80, "contact_ok": True, "reading_order_ok": True,
                "keyword_coverage": 0.8, "missing_keywords": [], "warnings": [],
            },
            "blocks_used": block_ids,
            "cut_lines": [],
            "interview_prep": [],
        }

    monkeypatch.setattr(resume_routes, "generate_resume", fake_generate_resume)

    app = create_app(db_path=str(db_path))
    tc = TestClient(app)

    body = {"block_ids": ["header-contact", "summary-main"], "accepted_rephrasings": []}
    resp = tc.post(f"/api/jobs/{job_id}/resume/generate", json=body)

    assert resp.status_code == 200
    result = resp.json()
    assert result["resume_id"] == 8
    assert captured["block_ids"] == ["header-contact", "summary-main"]
    assert captured["layout"] is None


def test_generate_with_unknown_layout_segment_id_returns_422(tmp_path):
    """A `layout` entry referencing a segment_id that doesn't exist must
    surface as a 422 (bad user input), not a bare 500. Exercises the real
    (non-monkeypatched) generate_resume/`_resolve_layout` path — the
    ValueError it raises happens in step (a), before any LaTeX rendering,
    so no fake render_pdf/ats_check/fit_to_page is needed here."""
    db_path = tmp_path / "t.db"
    job_id = _seed_job(db_path)

    app = create_app(db_path=str(db_path))
    tc = TestClient(app)

    body = {
        "block_ids": [],
        "accepted_rephrasings": [],
        "layout": [{"segment_id": "does-not-exist"}],
    }
    resp = tc.post(f"/api/jobs/{job_id}/resume/generate", json=body)

    assert resp.status_code == 422
    assert "does-not-exist" in resp.json()["detail"]
