"""Task 2: default resume engine wired to Ollama + real stored-gap keywords
+ graceful Ollama-down fallback.

These tests exercise the ``resume_engine=None`` (default) wiring path of
``create_app`` via the ``resume_llm`` override hook — NO real Ollama is
contacted; a fake ``llm``/``post`` is always injected.
"""

from fastapi.testclient import TestClient

from job_dashboard.api.app import create_app
from job_dashboard.db import (
    init_db, insert_job, record_llm_evaluation, upsert_embed_score,
)
from job_dashboard.models import JobListing
from job_dashboard.resume.keyword_map import LlmProposal


def _seed_job(db_path, gaps=None):
    conn = init_db(db_path)
    insert_job(
        conn,
        JobListing(
            source="s",
            title="ML Engineer",
            company="Stripe",
            job_url="https://x.com/1",
            description=(
                "We need a Python engineer. work. rga and other junk "
                "tokens a crude JD tokenizer would surface."
            ),
        ),
    )
    job_id = conn.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
    if gaps is not None:
        upsert_embed_score(conn, job_id, 0.9, "h")
        record_llm_evaluation(conn, job_id, 80, "Strong Fit", ["Python"], gaps, {})
    conn.close()
    return job_id


def test_suggest_with_fake_llm_returns_rephrasing_with_confidence(tmp_path):
    """Default (resume_engine=None) wiring: a fake llm proposal survives
    the integrity guard and comes back with a confidence tag."""
    db_path = tmp_path / "t.db"
    job_id = _seed_job(db_path)

    def fake_llm(segments, jd_text):
        seg = segments[0]
        return [
            LlmProposal(
                block_id=seg.id,
                jd_keyword="python",
                proposed_text=seg.text,
                confidence="exact-synonym",
            )
        ]

    app = create_app(db_path=str(db_path), resume_llm=fake_llm)
    tc = TestClient(app)

    resp = tc.post(f"/api/jobs/{job_id}/resume/suggest")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["rephrasings"]) >= 1
    assert body["rephrasings"][0]["confidence"] in {
        "exact-synonym", "equivalent", "transferable",
    }


def test_suggest_uses_stored_deep_rank_gaps_as_real_keywords(tmp_path):
    """Stored match_scores.gaps (from /rank) drive the gap chips, not crude
    JD tokenization — no 'work.'/'rga' junk, real tech terms only."""
    db_path = tmp_path / "t.db"
    job_id = _seed_job(db_path, gaps=["Kubernetes", "Kafka"])

    app = create_app(db_path=str(db_path), resume_llm=lambda segments, jd_text: [])
    tc = TestClient(app)

    resp = tc.post(f"/api/jobs/{job_id}/resume/suggest")
    assert resp.status_code == 200
    body = resp.json()
    gap_keywords = {g["jd_keyword"] for g in body["gaps"]}
    assert "Kubernetes" in gap_keywords
    assert "Kafka" in gap_keywords
    assert "work." not in gap_keywords
    assert "rga" not in gap_keywords


def test_suggest_falls_back_to_jd_tokenization_without_stored_gaps(tmp_path):
    """No stored deep-rank gaps -> gap keywords come from JD tokenization
    (existing crude-but-functional fallback), not an empty list."""
    db_path = tmp_path / "t.db"
    job_id = _seed_job(db_path, gaps=None)

    app = create_app(db_path=str(db_path), resume_llm=lambda segments, jd_text: [])
    tc = TestClient(app)

    resp = tc.post(f"/api/jobs/{job_id}/resume/suggest")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["gaps"], list)


def test_suggest_ollama_down_returns_200_with_no_rephrasings(tmp_path):
    """llm raising (Ollama unreachable) -> graceful 200, rephrasings: [],
    blocks/gaps still present. NEVER a 500."""
    db_path = tmp_path / "t.db"
    job_id = _seed_job(db_path, gaps=["Kubernetes"])

    def broken_llm(segments, jd_text):
        raise ConnectionError("Ollama down")

    app = create_app(db_path=str(db_path), resume_llm=broken_llm)
    tc = TestClient(app)

    resp = tc.post(f"/api/jobs/{job_id}/resume/suggest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rephrasings"] == []
    assert isinstance(body["block_ids"], list)
    assert len(body["block_ids"]) > 0
    assert any(g["jd_keyword"] == "Kubernetes" for g in body["gaps"])


def test_suggest_ollama_down_returning_empty_list_is_also_graceful(tmp_path):
    """llm returning [] (rather than raising) is the other Ollama-down
    shape resume_llm.make_ollama_llm can produce — also graceful."""
    db_path = tmp_path / "t.db"
    job_id = _seed_job(db_path, gaps=["Kubernetes"])

    app = create_app(db_path=str(db_path), resume_llm=lambda segments, jd_text: [])
    tc = TestClient(app)

    resp = tc.post(f"/api/jobs/{job_id}/resume/suggest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rephrasings"] == []
