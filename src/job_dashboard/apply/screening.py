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

import json
from pathlib import Path
import re
from typing import Callable

from job_dashboard.letter.draft import make_default_llm
from job_dashboard.letter.grounding import check_grounding

LlmFn = Callable[[str], str]

_MAX_PROFILE_CHARS = 1200
_MAX_PAGE_CHARS = 6000
_MAX_STORY_CHARS = 2500


def _facts_block(research) -> str:
    facts = getattr(research, "facts", None) or []
    lines = [
        f"- {getattr(f, 'text', '')} (source: {getattr(f, 'source_url', '')})"
        for f in facts if getattr(f, "text", "")
    ]
    return "\n".join(lines) or "(none)"


_INGREDIENTS = Path(__file__).resolve().parents[3] / "data" / "answer_style" / "ingredients.json"
_STOP = {"the", "and", "for", "with", "you", "your", "our", "are", "this", "that", "what", "why", "how", "have"}


def _words(text) -> set:
    return {w for w in re.findall(r"[a-z0-9+#]{3,}", str(text).lower()) if w not in _STOP}


def _project_blocks(question, job, limit: int = 2) -> str:
    """The 1-2 projects / roles most relevant to THIS question and job, each as its own labelled block, so the
    model never blends facts from different projects. Ranked by word overlap with the unit's title, tags and tech; education units are not projects. "" when the ingredient bank is missing."""
    try:
        units = json.loads(_INGREDIENTS.read_text()).get("units", [])
    except (OSError, ValueError):
        return ""
    job = job if isinstance(job, dict) else {}
    want = _words(f"{question} {job.get('title') or ''} {(job.get('description') or '')[:1500]}")
    scored = []
    for i, u in enumerate(x for x in units if x.get("type") in ("project", "work_experience")):
        have = _words(" ".join([u.get("title", ""), " ".join(u.get("tags", [])),
                                " ".join(u["tech"]) if isinstance(u.get("tech"), list) else str(u.get("tech", ""))]))
        scored.append((-len(want & have), i, u))
    blocks = []
    for n, (_, _, u) in enumerate(sorted(scored, key=lambda t: t[:2])[:limit], 1):
        impact = "; ".join(u["impact"]) if isinstance(u.get("impact"), list) else u.get("impact", "")
        blocks.append(f"PROJECT {n} — {u.get('title', '')} ({u.get('org', '')})\n"
                      f"  Problem: {u.get('problem', '')}\n  Approach: {u.get('approach', '')}\n"
                      f"  Impact: {impact}\n  Verbatim from résumé: {u.get('source', '')}")
    return "\n\n".join(blocks)


def _projects_section(question, job) -> str:
    blocks = _project_blocks(question, job)
    return f"THE CANDIDATE'S PROJECTS (ground truth, kept apart):\n{blocks}\n\n" if blocks else ""


def _build_prompt(job, question, profile_text, research, resume_text, story_text="") -> str:
    company = (job.get("company") if isinstance(job, dict) else None) or "the company"
    title = (job.get("title") if isinstance(job, dict) else None) or "the role"
    has_story = bool(story_text and story_text.strip())
    own_words = (
        f"IN THE CANDIDATE'S OWN WORDS:\n{story_text[:_MAX_STORY_CHARS]}\n\n"
        if has_story else ""
    )
    profile_source = "CANDIDATE PROFILE / OWN WORDS" if has_story else "CANDIDATE PROFILE"
    return (
        "You are answering ONE free-text question on a job application, in the "
        "candidate's own voice. Answer truthfully in 4-6 sentences.\n\n"
        "STRICT RULES (truthfulness is mandatory):\n"
        f"1. Ground every claim about the candidate in the {profile_source} "
        "below. Never invent an achievement, tool, or metric.\n"
        "2. Mention a company-specific detail ONLY if it appears in COMPANY & "
        "ROLE or VERIFIED COMPANY FACTS. Never invent a company fact.\n"
        "3. Be concrete and specific; no generic filler.\n"
        "4. Connect what the candidate says they want and enjoy to what this "
        "company does. Warm, specific, first person; no generic filler.\n"
        "5. Each PROJECT block is a SEPARATE project. Draw on at most two, never blend them: a tool, number or "
        "outcome belongs only to the project whose block states it. Name the project when you cite it.\n\n"
        f"ROLE: {title} at {company}\n"
        f"QUESTION: {question}\n\n"
        f"CANDIDATE PROFILE (overview only; specifics come from the PROJECT blocks):\n{(profile_text or '')[:_MAX_PROFILE_CHARS]}\n\n"
        f"{_projects_section(question, job)}"
        f"{own_words}"
        f"COMPANY & ROLE (from the job page):\n{(resume_text or '')[:_MAX_PAGE_CHARS]}\n\n"
        f"VERIFIED COMPANY FACTS (the ONLY source for company specifics):\n"
        f"{_facts_block(research)}\n\n"
        'Reply with ONLY a JSON object: {"answer": "<the answer text>", '
        '"confidence": <0-100, how sure you are this answers the question '
        'correctly from the material above; low if you had to guess>, '
        '"basis": "<one short line: what the answer rests on>"}'
    )


def _parse_reply(raw: str):
    """(answer, confidence, basis). A reply that isn't the requested JSON keeps
    its raw text as the answer with confidence None (unknown)."""
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    try:
        d = json.loads(m.group(0)) if m else None
        ans = d["answer"].strip() if isinstance(d, dict) and isinstance(d.get("answer"), str) else None
    except ValueError:
        ans = d = None
    if not ans:
        return text, None, None
    try:
        conf = max(0, min(100, int(d.get("confidence"))))
    except (TypeError, ValueError):
        conf = None
    basis = d.get("basis") if isinstance(d.get("basis"), str) else None
    return ans, conf, basis


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


def draft_screening_answer(job, question, profile_text, research, resume_text="", llm=None,
                           story_text=""):
    """Draft a grounded answer to a single screening question.

    Returns ``{"answer", "flags", "unsupported_company_claims", "confidence"
    (0-100 or None=unknown), "basis", "prompt"}``. ``flags`` carries
    ``"general_fallback"`` when the llm was unavailable/unusable and a general
    (still truthful) answer was returned instead. ``story_text`` is the
    candidate's own long-form answers (qbank topic=story) -- own-words context
    for drafting only, never a value filled verbatim into a form. Never raises.
    """
    llm_fn = llm or make_default_llm()
    answer, flags, confidence, basis, prompt = None, [], None, None, ""
    try:
        prompt = _build_prompt(job, question, profile_text, research, resume_text, story_text)
        candidate = llm_fn(prompt)
        if isinstance(candidate, str) and candidate.strip():
            answer, confidence, basis = _parse_reply(candidate)
            answer = answer or None
    except Exception:
        answer = None
    if answer is None:
        answer = _general_answer(job, profile_text)
        flags = ["general_fallback"]

    # Post-hoc grounding check (parity with the cover-letter guard): flag any
    # company-specific claim in the answer that traces to neither the research
    # bundle nor the profile/JD. Best-effort code check; the human reviews the
    # answer before it is filled (runbook step 4). Prompt-only grounding is not
    # enough on its own -- an off-prompt/hallucinated fact would otherwise reach
    # the user unflagged.
    try:
        job_text = " ".join(
            str(job.get(k) or "") for k in ("title", "company", "description")
        ) if isinstance(job, dict) else ""
        grounding_text = (profile_text or "") + "\n" + (story_text or "")
        unsupported = check_grounding(answer, research, grounding_text, job_text
                                      ).unsupported_company_claims
    except Exception:
        unsupported = []
    return {"answer": answer, "flags": flags, "unsupported_company_claims": unsupported,
            "confidence": confidence, "basis": basis, "prompt": prompt}
