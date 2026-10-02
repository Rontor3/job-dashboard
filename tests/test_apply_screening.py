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


def test_post_hoc_grounding_flags_fabricated_company_figure():
    # A hallucinated "$900M" absent from research/profile/JD must be flagged,
    # even though the prompt told the model not to invent it (defense in depth).
    out = draft_screening_answer(
        JOB, "Why us?", "I build ML systems.",
        ResearchBundle([Fact("Acme is a fraud startup.", "http://a")], [], False),
        llm=lambda p: "I admire that Acme raised $900M last year.",
    )
    assert any("$900M" in c for c in out["unsupported_company_claims"])


def test_grounded_answer_has_no_unsupported_claims():
    out = draft_screening_answer(
        JOB, "Why us?", "I build ML systems.",
        ResearchBundle([Fact("Acme cut fraud losses 40%.", "http://a")], [], False),
        llm=lambda p: "I'm drawn to how Acme cut fraud losses 40%.",
    )
    assert out["unsupported_company_claims"] == []


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


def test_json_reply_yields_confidence_and_basis():
    r = draft_screening_answer(
        JOB, "Why us?", "profile", ResearchBundle([], [], True),
        llm=lambda p: '<think>hm</think>{"answer": "Fraud work fits.", "confidence": 82, "basis": "Tata AIG project"}')
    assert (r["answer"], r["confidence"], r["basis"]) == ("Fraud work fits.", 82, "Tata AIG project")
    assert "Why us?" in r["prompt"]


def test_plain_reply_keeps_text_with_unknown_confidence():
    r = draft_screening_answer(JOB, "Why us?", "profile", ResearchBundle([], [], True),
                               llm=lambda p: "Just prose.")
    assert r["answer"] == "Just prose." and r["confidence"] is None


def test_confidence_clamped_and_bad_value_unknown():
    mk = lambda c: (lambda p: '{"answer": "a", "confidence": %s}' % c)
    b = ResearchBundle([], [], True)
    assert draft_screening_answer(JOB, "q", "p", b, llm=mk(250))["confidence"] == 100
    assert draft_screening_answer(JOB, "q", "p", b, llm=mk('"high"'))["confidence"] is None


def test_prompt_has_own_words_and_company_page():
    from job_dashboard.apply.screening import _build_prompt
    job = {"title": "ML Engineer", "company": "HUD", "description": "HUD builds RL environments for agents. " * 80}
    p = _build_prompt(job, "Why HUD?", "Data scientist", None, job["description"], "Q: Why startups?\nA: Ownership.")
    assert "IN THE CANDIDATE'S OWN WORDS" in p and "A: Ownership." in p
    assert "COMPANY & ROLE (from the job page)" in p and "RESUME EXCERPT" not in p
    assert p.count("HUD builds RL environments") > 10          # 2000-char page window, not 800


def test_prompt_omits_own_words_when_empty():
    from job_dashboard.apply.screening import _build_prompt
    job = {"title": "ML Engineer", "company": "HUD", "description": "HUD builds RL environments for agents. " * 80}
    assert "OWN WORDS" not in _build_prompt(job, "Why HUD?", "x", None, "", "")


def test_draft_passes_story_to_prompt():
    job = {"title": "ML Engineer", "company": "HUD", "description": "HUD builds RL environments for agents. " * 80}
    seen = []
    res = draft_screening_answer(job, "Why HUD?", "Data scientist", None, job["description"],
                                 llm=lambda p: seen.append(p) or '{"answer": "Because.", "confidence": 80, "basis": "b"}',
                                 story_text="Q: Why startups?\nA: Ownership.")
    assert "A: Ownership." in seen[0] and res["answer"] == "Because."
