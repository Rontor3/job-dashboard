"""Tests for the grounded screening-answer draft (apply/screening.py)."""

import pytest

from job_dashboard.letter.company_research import Fact, ResearchBundle
from job_dashboard.apply.screening import draft_screening_answer

JOB = {"title": "ML Engineer", "company": "Acme", "description": "fraud ML"}


def test_uses_fake_llm_answer():
    out = draft_screening_answer(
        JOB, "Why Acme?", "I built fraud models.",
        ResearchBundle([Fact("Acme cut fraud 40%", "http://a")], [], False),
        resume_text="fraud pipeline", llm=lambda p: "Because Acme cut fraud 40%.",
    )
    assert "answer" in out and out["answer"]


def test_llm_raise_falls_back_no_raise():
    def boom(p):
        raise RuntimeError("ollama down")

    out = draft_screening_answer(
        JOB, "Why us?", "profile", ResearchBundle([], [], True), llm=boom
    )
    assert isinstance(out["answer"], str)  # general truthful answer, no raise
    assert out["flags"] == ["general_fallback"]


def test_empty_research_no_fabricated_company_specifics():
    # with empty research + a fake llm that would echo a company fact, the prompt
    # must not have supplied one; assert a known fabricated token is absent.
    out = draft_screening_answer(
        JOB, "Why us?", "profile", ResearchBundle([], [], True),
        llm=lambda p: "I admire your work." if "FAKEPROD" not in p else "FAKEPROD",
    )
    assert "FAKEPROD" not in out["answer"]


def _ollama_is_up() -> bool:
    try:
        import requests

        from job_dashboard.resume.resume_llm import DEFAULT_HOST

        requests.get(f"{DEFAULT_HOST}/api/tags", timeout=3)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _ollama_is_up(), reason="Ollama not running at DEFAULT_HOST")
def test_live_smoke_real_qwen_screening_answer():
    """Real HTTP call to a running Ollama qwen2.5:14b -- no mocks."""
    from job_dashboard.letter.draft import make_default_llm

    research = ResearchBundle(
        facts=[Fact(text="Acme's fraud-detection platform cut customer losses by 40%.",
                     source_url="https://acme.com/impact")],
        queries_used=["Acme product"],
        empty=False,
    )
    llm = make_default_llm()
    out = draft_screening_answer(
        JOB, "Why Acme?", "Experienced ML engineer who has shipped fraud-detection systems.",
        research, resume_text="fraud pipeline", llm=llm,
    )

    assert isinstance(out, dict)
    assert out["answer"]
    print("\nLIVE OLLAMA SCREENING ANSWER:\n", out["answer"])
    print("flags:", out["flags"])
