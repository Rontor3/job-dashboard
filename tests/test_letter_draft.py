"""Tests for the grounded cover-letter draft (draft.py)."""

import os

import pytest

from job_dashboard.letter.company_research import Fact, ResearchBundle
from job_dashboard.letter.draft import draft_cover_letter, make_default_llm

_FACT_TEXT = "Acme's fraud platform cut losses 40% ($200M saved)."
_FACT_URL = "https://acme.com/impact"

_JOB = {
    "title": "ML Engineer",
    "company": "Acme",
    "description": "Build fraud detection models at scale.",
    "strengths": ["shipped production ML pipelines", "led a 3-person team"],
}

# A token a hallucinating LLM might fabricate for a company it has zero
# verified facts about -- must never appear in output when research is empty.
_FABRICATED_TOKEN = "QuantumFlow raised $500M in Series Z funding"


def _bundle_with_fact():
    return ResearchBundle(
        facts=[Fact(text=_FACT_TEXT, source_url=_FACT_URL)],
        queries_used=["Acme product"],
        empty=False,
    )


def _empty_bundle():
    return ResearchBundle(facts=[], queries_used=["Acme product"], empty=True)


def test_fake_llm_referencing_a_fact_is_reflected_in_company_facts_used():
    def fake_llm(prompt: str) -> str:
        assert _FACT_TEXT in prompt  # the fact was actually in the grounding prompt
        return (
            "Dear Hiring Manager,\n\n"
            f"I was drawn to Acme after learning that {_FACT_TEXT} "
            "Given my background in shipped production ML pipelines, "
            "I'm confident I can contribute similar impact.\n\n"
            "Sincerely,\n[Your Name]"
        )

    result = draft_cover_letter(_JOB, "profile text here", _bundle_with_fact(), "confident", llm=fake_llm)

    assert _FACT_TEXT in result["body"]
    assert result["company_facts_used"] == [{"text": _FACT_TEXT, "source_url": _FACT_URL}]
    assert result["flags"] == []


def test_empty_research_never_calls_llm_and_has_no_fabricated_company_specifics():
    calls = []

    def fake_llm(prompt: str) -> str:
        calls.append(prompt)
        # A misbehaving LLM that would fabricate company specifics if asked.
        return f"Dear Hiring Manager,\n\n{_FABRICATED_TOKEN}.\n\nSincerely,\n[Your Name]"

    result = draft_cover_letter(_JOB, "profile text here", _empty_bundle(), "confident", llm=fake_llm)

    assert calls == []  # llm never invoked -- structural guarantee, not just a prompt
    assert _FABRICATED_TOKEN not in result["body"]
    assert "QuantumFlow" not in result["body"]
    assert "$" not in result["body"]
    assert "%" not in result["body"]
    assert result["company_facts_used"] == []
    assert result["body"]  # still a real, non-empty letter


def test_llm_raising_returns_general_body_without_raising():
    def boom(prompt: str) -> str:
        raise RuntimeError("Ollama connection refused")

    result = draft_cover_letter(_JOB, "profile text here", _bundle_with_fact(), "confident", llm=boom)

    assert result["body"]
    assert result["company_facts_used"] == []
    assert "general_template" in result["flags"][0]
    # No company-specific figures leaked into the safety-net template either.
    assert "$" not in result["body"]
    assert "%" not in result["body"]


def test_llm_returning_blank_string_falls_back_to_general_body():
    result = draft_cover_letter(_JOB, "profile text here", _bundle_with_fact(), None, llm=lambda p: "   ")

    assert result["body"]
    assert result["company_facts_used"] == []
    assert result["flags"] == ["general_template:llm_unavailable"]


def test_general_template_uses_real_stored_strengths():
    result = draft_cover_letter(_JOB, "profile text", _empty_bundle(), None, llm=lambda p: "")

    assert "shipped production ML pipelines" in result["body"]
    assert "led a 3-person team" in result["body"]


def test_malformed_job_never_raises():
    result = draft_cover_letter("not a dict", "profile", _empty_bundle(), None, llm=lambda p: "x")

    assert isinstance(result, dict)
    assert result["body"]
    assert result["company_facts_used"] == []


def _ollama_is_up() -> bool:
    try:
        import requests

        from job_dashboard.resume.resume_llm import DEFAULT_HOST

        requests.get(f"{DEFAULT_HOST}/api/tags", timeout=3)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _ollama_is_up(), reason="Ollama not running at DEFAULT_HOST")
def test_live_smoke_real_qwen_draft_references_a_bundle_fact():
    """Real HTTP call to a running Ollama qwen2.5:14b -- no mocks.

    Small fake research bundle (1-2 facts); asserts a non-empty body and
    prints the letter for human review of the report.
    """
    research = ResearchBundle(
        facts=[
            Fact(
                text="Acme's fraud-detection platform cut customer losses by 40% last year.",
                source_url="https://acme.com/impact",
            ),
            Fact(
                text="Acme raised a $60M Series C to expand its risk platform.",
                source_url="https://acme.com/press",
            ),
        ],
        queries_used=["Acme product", "Acme revenue funding milestone"],
        empty=False,
    )

    llm = make_default_llm()
    result = draft_cover_letter(
        _JOB, "Experienced ML engineer who has shipped fraud-detection systems at scale.",
        research, "confident, direct", llm=llm,
    )

    assert isinstance(result, dict)
    assert result["body"]
    print("\nLIVE OLLAMA COVER LETTER DRAFT:\n", result["body"])
    print("\ncompany_facts_used:", result["company_facts_used"])
    print("flags:", result["flags"])
