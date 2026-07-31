"""Grounded screening-answer draft for the Application Agent.

Answers ONE page-specific free-text application question ("Why us?", "Describe a
project") in the candidate's voice, grounded strictly in the candidate profile /
resume / company-research bundle. Reuses the cover-letter Ollama seam
(``letter.draft.make_default_llm``). Never fabricates a company specific: if the
research bundle is empty the prompt supplies no company facts, so the model has
nothing to invent from. Any llm failure or empty response falls back to a
general, truthful answer assembled from the profile. This function NEVER raises.
"""
from __future__ import annotations

from typing import Callable

from job_dashboard.letter.draft import make_default_llm

LlmFn = Callable[[str], str]

_MAX_PROFILE_CHARS = 1200
_MAX_RESUME_CHARS = 800


def _facts_block(research) -> str:
    facts = getattr(research, "facts", None) or []
    lines = [
        f"- {getattr(f, 'text', '')} (source: {getattr(f, 'source_url', '')})"
        for f in facts if getattr(f, "text", "")
    ]
    return "\n".join(lines) or "(none)"


def _build_prompt(job, question, profile_text, research, resume_text) -> str:
    company = (job.get("company") if isinstance(job, dict) else None) or "the company"
    title = (job.get("title") if isinstance(job, dict) else None) or "the role"
    return (
        "You are answering ONE free-text question on a job application, in the "
        "candidate's own voice. Answer truthfully in 3-5 sentences.\n\n"
        "STRICT RULES (truthfulness is mandatory):\n"
        "1. Ground every claim about the candidate in the CANDIDATE PROFILE / "
        "RESUME below. Never invent an achievement, tool, or metric.\n"
        "2. Mention a company-specific detail ONLY if it appears verbatim in "
        "VERIFIED COMPANY FACTS. If that list is empty, do NOT mention any "
        "company product, figure, or milestone -- answer about genuine interest "
        "and fit instead. Never invent a company fact.\n"
        "3. Be concrete and specific; no generic filler.\n\n"
        f"ROLE: {title} at {company}\n"
        f"QUESTION: {question}\n\n"
        f"CANDIDATE PROFILE:\n{(profile_text or '')[:_MAX_PROFILE_CHARS]}\n\n"
        f"RESUME EXCERPT:\n{(resume_text or '')[:_MAX_RESUME_CHARS]}\n\n"
        f"VERIFIED COMPANY FACTS (the ONLY source for company specifics):\n"
        f"{_facts_block(research)}\n\n"
        "Write only the answer text."
    )


def _general_answer(job, profile_text) -> str:
    title = (job.get("title") if isinstance(job, dict) else None) or ""
    role = f"the {title} position" if title.strip() else "this role"
    if profile_text and profile_text.strip():
        return (
            f"I'm genuinely excited about {role}. My background gives me directly "
            "relevant, hands-on experience for its core requirements, and I'm "
            "confident I can contribute meaningfully while continuing to grow "
            "with the team."
        )
    return (
        f"I'm genuinely excited about {role} and believe my experience aligns "
        "well with what the team needs. I'd welcome the chance to contribute and "
        "grow here."
    )


def draft_screening_answer(job, question, profile_text, research, resume_text="", llm=None):
    """Draft a grounded answer to a single screening question.

    Returns ``{"answer": str, "flags": list}``. ``flags`` carries
    ``"general_fallback"`` when the llm was unavailable/unusable and a general
    (still truthful) answer was returned instead. Never raises.
    """
    llm_fn = llm or make_default_llm()
    try:
        prompt = _build_prompt(job, question, profile_text, research, resume_text)
        answer = llm_fn(prompt)
        if isinstance(answer, str) and answer.strip():
            return {"answer": answer.strip(), "flags": []}
    except Exception:
        pass
    return {"answer": _general_answer(job, profile_text), "flags": ["general_fallback"]}
