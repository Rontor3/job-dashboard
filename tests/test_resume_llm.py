"""Tests for the Ollama LlmFn adapter (resume_llm.make_ollama_llm)."""

from pathlib import Path

import pytest

from job_dashboard.resume.keyword_map import LlmProposal
from job_dashboard.resume.resume_llm import DEFAULT_HOST, make_ollama_llm
from job_dashboard.resume.segments import Segment


def _seg(id, text, tags):
    return Segment(
        id=id,
        kind="project",
        title=id,
        tags=tags,
        tex_path=Path(id),
        text=text,
        exclusive_group=None,
    )


def test_ollama_llm_maps_keyword_to_proposal():
    segs = [
        _seg(
            "p-rag",
            r"\item Built offline RAG with Ollama + sentence-transformers embeddings",
            ["rag", "embeddings"],
        )
    ]
    calls = []

    def fake_post(url, json_body):
        calls.append(json_body)
        return {
            "response": (
                '{"proposed_text": "Implemented vector search using '
                'sentence-transformers embeddings", "confidence": "exact-synonym"}'
            )
        }

    llm = make_ollama_llm(post=fake_post)
    props = llm(segs, "We need vector search experience")
    assert any(
        isinstance(p, LlmProposal) and p.jd_keyword and "vector" in p.proposed_text.lower()
        for p in props
    )
    assert calls and calls[0]["model"]  # model set, format=json used
    assert calls[0].get("format") == "json"


def test_ollama_llm_returns_empty_on_http_error():
    segs = [_seg("p", r"\item x", ["x"])]

    def boom(url, json_body):
        raise RuntimeError("connection refused")

    props = make_ollama_llm(post=boom)(segs, "need kafka")
    assert props == []


def test_ollama_llm_skips_unparseable_response():
    segs = [_seg("p", r"\item Python microservices", ["python"])]

    def bad(url, json_body):
        return {"response": "not json at all"}

    props = make_ollama_llm(post=bad)(segs, "need python and go")
    assert props == []  # nothing parseable -> no proposals, no raise


def _ollama_is_up() -> bool:
    try:
        import requests

        requests.get(f"{DEFAULT_HOST}/api/tags", timeout=3)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _ollama_is_up(), reason="Ollama not running at DEFAULT_HOST")
def test_ollama_llm_live_smoke():
    """Real HTTP call to a running Ollama qwen2.5:14b — no mocks.

    Only asserts the adapter never raises and returns a list. The actual
    text is printed to stdout (run with -s) so a human can eyeball the
    model's real rephrasing for the report.
    """
    segs = [
        _seg(
            "p-rag",
            r"\item Built offline RAG with Ollama + sentence-transformers embeddings",
            ["rag", "embeddings"],
        )
    ]

    llm = make_ollama_llm()
    props = llm(segs, "We need vector search experience")

    assert isinstance(props, list)
    assert len(props) >= 0
    for p in props:
        assert isinstance(p, LlmProposal)
    print("\nLIVE OLLAMA SMOKE RESULT:", props)
