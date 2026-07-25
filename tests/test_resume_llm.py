"""Tests for the Ollama LlmFn adapter (resume_llm.make_ollama_llm)."""

from pathlib import Path

import pytest

from job_dashboard.resume.keyword_map import LlmProposal
from job_dashboard.resume.resume_llm import (
    DEFAULT_HOST, extract_jd_keywords, make_ollama_llm,
)
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


def test_extract_jd_keywords_parses_clean_list_from_fake_post():
    def fake_post(url, json_body):
        return {"response": '{"keywords": ["kubernetes", "pytorch"]}'}

    kws = extract_jd_keywords("We need K8s and deep learning experience.", post=fake_post)
    assert kws == ["kubernetes", "pytorch"]


def test_extract_jd_keywords_returns_empty_on_post_raising():
    def boom(url, json_body):
        raise RuntimeError("connection refused")

    assert extract_jd_keywords("some JD text", post=boom) == []


def test_extract_jd_keywords_returns_empty_on_unparseable_response():
    def bad(url, json_body):
        return {"response": "not json at all"}

    assert extract_jd_keywords("some JD text", post=bad) == []


def test_extract_jd_keywords_returns_empty_on_missing_keywords_field():
    def no_keywords(url, json_body):
        return {"response": '{"proposed_text": "x", "confidence": "equivalent"}'}

    assert extract_jd_keywords("some JD text", post=no_keywords) == []


def test_extract_jd_keywords_dedupes_lowercases_and_caps():
    def fake_post(url, json_body):
        return {
            "response": (
                '{"keywords": ["Kubernetes", "kubernetes", "Pytorch", '
                '"Docker", "1", "2", "3", "4", "5", "6", "7", "8", "9", '
                '"10", "11", "12"]}'
            )
        }

    kws = extract_jd_keywords("JD text", post=fake_post)
    assert kws[:3] == ["kubernetes", "pytorch", "docker"]
    assert len(kws) <= 15


def test_ollama_llm_reword_attempts_use_clean_extracted_keywords_not_raw_jd_junk():
    """The actual keyword-SOURCE fix: llm() must drive reword attempts off
    extract_jd_keywords' clean output, not a crude regex tokenization of
    jd_text (which would surface junk like "work."/"rga")."""
    segs = [
        _seg(
            "p-cicd",
            r"\item Built CI/CD pipelines and containerized services",
            ["cicd"],
        )
    ]
    calls = []

    def fake_post(url, json_body):
        calls.append(json_body)
        prompt = json_body["prompt"]
        if "Extract the concrete technical skills" in prompt:
            return {"response": '{"keywords": ["docker"]}'}
        return {
            "response": (
                '{"proposed_text": "Built CI/CD pipelines and containerized '
                'services with Docker", "confidence": "exact-synonym"}'
            )
        }

    llm = make_ollama_llm(post=fake_post)
    jd_text = "5+ years required. work. rga and other junk tokens. We use Docker heavily."
    props = llm(segs, jd_text)

    assert any(p.jd_keyword == "docker" for p in props)
    reword_calls = [
        c for c in calls if "Extract the concrete technical skills" not in c["prompt"]
    ]
    assert reword_calls  # at least one reword attempt was made
    for c in reword_calls:
        assert "work." not in c["prompt"].split("keyword to surface")[-1]
        assert "rga" not in c["prompt"].split("keyword to surface")[-1]


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
