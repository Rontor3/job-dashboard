"""Grounded qwen cover-letter draft — the integrity-critical half of the pair
with :mod:`job_dashboard.letter.grounding`.

``draft_cover_letter`` connects the candidate's REAL strengths (the job's
stored deep-rank ``strengths`` plus ``profile_text``) to company-specific,
role-relevant impact drawn ONLY from ``research.facts``. The model call is
injected as ``llm(prompt: str) -> str``; the default reuses the same
Ollama host/model env-var seam as ``resume_llm.make_ollama_llm``
(``OLLAMA_HOST`` / ``OLLAMA_MODEL``, lazy ``requests`` import).

Integrity guarantee — structural, not just prompted:

- If ``research`` is empty (no facts), the LLM is never even called for
  company specifics. This function returns a deterministic general-template
  body instead: real role + real candidate strengths, zero company-specific
  claims (no company name, product, funding figure, $, or %). A poorly
  behaved ``llm`` cannot fabricate what it is never asked to write.
- If a non-empty ``research`` bundle IS available, the prompt instructs the
  model to reference a company fact only if it is copied from
  ``research.facts``, but that instruction is a courtesy, not a guarantee
  (same caveat as ``resume_llm``'s prompts) — ``grounding.check_grounding``
  is the best-effort code-side scan, and the dashboard panel is the
  authoritative human review step.
- ANY ``llm`` failure (raises, returns non-string, returns empty/blank) is
  caught and falls back to the same general template. This function NEVER
  raises.

``company_facts_used`` is computed by checking which of ``research.facts``
actually appear (fact text or source_url as a literal substring) in the
returned body — never a claim about what the model "meant" to use.
"""

from __future__ import annotations

import os
from typing import Callable

from job_dashboard.letter.company_research import Fact, ResearchBundle
from job_dashboard.resume.resume_llm import DEFAULT_HOST, DEFAULT_MODEL

LlmFn = Callable[[str], str]
PostFn = Callable[[str, dict], dict]

# Bound on how many stored strengths / profile chars feed the prompt.
_MAX_STRENGTHS = 6
_MAX_PROFILE_CHARS = 1500
_MAX_DESCRIPTION_CHARS = 800

_DEFAULT_WRITING_STYLE = "professional, confident, concise"


# --------------------------------------------------------------------------
# Default Ollama adapter (reuses resume_llm's host/model/post seam)
# --------------------------------------------------------------------------


def _default_post(url: str, json_body: dict) -> dict:
    import requests  # lazy import: only needed when actually calling Ollama

    return requests.post(url, json=json_body, timeout=60).json()


def make_default_llm(
    post: PostFn | None = None,
    model: str | None = None,
    host: str | None = None,
) -> LlmFn:
    """Build the default ``llm(prompt) -> str`` backed by a local Ollama
    ``/api/generate`` call. Same env-var seam as ``resume_llm.make_ollama_llm``
    (``OLLAMA_HOST`` / ``OLLAMA_MODEL``, falling back to
    ``resume_llm.DEFAULT_HOST`` / ``DEFAULT_MODEL``). May raise on HTTP or
    parsing failure — callers (``draft_cover_letter``) are responsible for
    catching that and falling back; this adapter itself stays thin.
    """
    resolved_host = host or os.getenv("OLLAMA_HOST", DEFAULT_HOST)
    resolved_model = model or os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
    post_fn = post or _default_post
    url = f"{resolved_host}/api/generate"

    def llm(prompt: str) -> str:
        body = {
            "model": resolved_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.4},
        }
        resp = post_fn(url, body)
        text = resp.get("response") if isinstance(resp, dict) else None
        if not isinstance(text, str):
            raise ValueError("Ollama response missing a string 'response' field")
        return text

    return llm


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _job_strengths(job: dict) -> list[str]:
    """Candidate strengths already stored on ``job`` (e.g. from deep-rank).

    Only real, previously-produced strings are used — this never invents a
    strength. Missing/malformed input just yields an empty list.
    """
    strengths = job.get("strengths") if isinstance(job, dict) else None
    if not isinstance(strengths, list):
        return []
    return [s.strip() for s in strengths if isinstance(s, str) and s.strip()][:_MAX_STRENGTHS]


def _general_template_body(job: dict, strengths: list[str]) -> str:
    """Deterministic fallback: real role + real candidate strengths, ZERO
    company-specific claims (no company name, product, funding, $, or %).
    Used whenever research is empty or the llm is unavailable/unusable —
    this is the safety net that makes the "never fabricate" guarantee
    structural rather than merely prompted.
    """
    title = job.get("title") if isinstance(job, dict) else None
    role_phrase = f"the {title} position" if isinstance(title, str) and title.strip() else "this position"

    if strengths:
        strength_line = "My background includes " + "; ".join(strengths) + "."
    else:
        strength_line = (
            "My background reflects strong, hands-on experience directly "
            "relevant to this role's core requirements."
        )

    return (
        "Dear Hiring Manager,\n\n"
        f"I am writing to express my genuine interest in {role_phrase}. "
        f"{strength_line} I take pride in delivering real, measurable "
        "impact, and I am confident that same rigor and care would "
        "translate directly to this role.\n\n"
        "I would welcome the opportunity to discuss how my experience "
        "could contribute to your team's goals, and I have attached my "
        "resume for further detail.\n\n"
        "Sincerely,\n"
        "[Your Name]"
    )


def _build_prompt(
    job: dict,
    profile_text: str,
    research: ResearchBundle,
    writing_style: str | None,
    strengths: list[str],
) -> str:
    company = job.get("company") if isinstance(job, dict) else None
    title = job.get("title") if isinstance(job, dict) else None
    description = job.get("description") if isinstance(job, dict) else None

    facts_block = "\n".join(
        f"- {f.text} (source: {f.source_url})" for f in research.facts
    ) or "(none)"
    strengths_block = "\n".join(f"- {s}" for s in strengths) or (
        "(none stored — infer real strengths only from the candidate profile below)"
    )
    style = writing_style if isinstance(writing_style, str) and writing_style.strip() else _DEFAULT_WRITING_STYLE

    return (
        "You are drafting the BODY of a cover letter (no header/date/address "
        "block, just paragraphs starting with 'Dear Hiring Manager,' and "
        "ending with a sign-off placeholder '[Your Name]').\n\n"
        "STRICT RULES (truthfulness is mandatory):\n"
        "1. Only claim candidate strengths that are grounded in the "
        "CANDIDATE STRENGTHS or CANDIDATE PROFILE sections below. Never "
        "invent an achievement, tool, or metric for the candidate.\n"
        "2. Only mention a company-specific detail (product, revenue, "
        "funding, milestone, or figure) if it is copied from VERIFIED "
        "COMPANY FACTS below. If that list is empty, do NOT mention any "
        "company product, funding, revenue, or dollar/percent figure — "
        "write a strong, genuine letter about interest in the role instead.\n"
        "3. Never invent a dollar figure, percentage, funding round, or "
        "product name that is not verbatim in VERIFIED COMPANY FACTS.\n"
        f"4. Write in this voice/style: {style}.\n\n"
        f"ROLE: {title or 'the role'} at {company or 'the company'}\n"
        f"JOB DESCRIPTION EXCERPT:\n{(description or '')[:_MAX_DESCRIPTION_CHARS]}\n\n"
        f"CANDIDATE STRENGTHS (prior analysis, all real):\n{strengths_block}\n\n"
        f"CANDIDATE PROFILE:\n{(profile_text or '')[:_MAX_PROFILE_CHARS]}\n\n"
        f"VERIFIED COMPANY FACTS (ONLY source for company specifics, quote "
        f"them closely when used):\n{facts_block}\n\n"
        "Write the cover letter body now, 3-4 paragraphs."
    )


def _facts_referenced(body: str, facts: list[Fact]) -> list[dict]:
    """The subset of ``facts`` that literally appear (text or source_url)
    in ``body`` — i.e. what the draft actually used, not what it "meant to".
    """
    used: list[dict] = []
    for fact in facts:
        text_hit = bool(fact.text) and fact.text in body
        url_hit = bool(fact.source_url) and fact.source_url in body
        if text_hit or url_hit:
            used.append({"text": fact.text, "source_url": fact.source_url})
    return used


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def draft_cover_letter(
    job: dict,
    profile_text: str,
    research: ResearchBundle | None,
    writing_style: str | None = None,
    llm: LlmFn | None = None,
) -> dict:
    """Draft a grounded cover letter body.

    Returns ``{"body": str, "company_facts_used": list[dict], "flags": list}``.
    NEVER raises: empty research skips the llm entirely (general template);
    any llm failure/empty response also falls back to the general template.
    """
    try:
        job = job if isinstance(job, dict) else {}
        strengths = _job_strengths(job)

        has_facts = (
            research is not None
            and not getattr(research, "empty", True)
            and bool(getattr(research, "facts", None))
        )
        if not has_facts:
            return {
                "body": _general_template_body(job, strengths),
                "company_facts_used": [],
                "flags": ["general_template:empty_research"],
            }

        llm_fn = llm or make_default_llm()
        try:
            prompt = _build_prompt(job, profile_text, research, writing_style, strengths)
            body = llm_fn(prompt)
        except Exception:
            body = None

        if not isinstance(body, str) or not body.strip():
            return {
                "body": _general_template_body(job, strengths),
                "company_facts_used": [],
                "flags": ["general_template:llm_unavailable"],
            }

        body = body.strip()
        return {
            "body": body,
            "company_facts_used": _facts_referenced(body, research.facts),
            "flags": [],
        }
    except Exception:
        # Absolute safety net: this function must never raise regardless of
        # malformed inputs. Fall back to the zero-company-specifics template.
        return {
            "body": _general_template_body({}, []),
            "company_facts_used": [],
            "flags": ["general_template:draft_error"],
        }
