"""Phase E judgment tier: answer the fields map_screen escalated, grounded in
profile + JD, as drafts behind the dry-run gate. LLM-free-testable (inject llm)."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class JudgmentContext:
    job: dict                      # {title, company, description}
    profile_text: str = ""
    research: object = None        # ResearchBundle or None (draft handles None)
    resume_text: str = ""


_SENSITIVE_RE = re.compile(
    r"\bgender\b|\bethnic|\brace\b|\bhispanic\b|\blatino\b|\bveteran\b|"
    r"\barmed forces\b|\bdisab|\bsexual orientation\b|\bpronoun", re.I)
_SENSITIVE_PURPOSES = {"veteran", "attestation"}


def _is_sensitive(field) -> bool:
    if field.purpose in _SENSITIVE_PURPOSES:
        return True
    return bool(_SENSITIVE_RE.search(field.label or ""))


def profile_to_text(profile) -> str:
    parts = []
    c = profile.contact or {}
    if c.get("full_name"):
        parts.append(f"Name: {c['full_name']}")
    for e in profile.experiences:
        head = f"{e.title} at {e.company} ({e.start}-{e.end})".strip()
        parts.append("Experience: " + head)
        for b in e.bullets:
            parts.append(f"  - {b}")
    for ed in profile.education:
        parts.append(f"Education: {ed.degree} {ed.field} at {ed.school}".strip())
    if profile.skills:
        parts.append("Skills: " + ", ".join(profile.skills))
    return "\n".join(parts)


def map_option(label, options, profile_text, llm) -> str | None:
    """Ask the llm to pick exactly one of `options` for the field, or NONE.
    Validates the reply against `options` (never returns a non-option)."""
    opts = [o for o in (options or [])
            if o and o.strip().lower() not in ("select an option", "select...")]
    if not opts:
        return None
    prompt = (
        "Pick the ONE option that best answers the application question for this "
        "candidate. Reply with the option text EXACTLY as written, or the word "
        "NONE if none fit.\n\n"
        f"QUESTION: {label}\nOPTIONS:\n" + "\n".join(f"- {o}" for o in opts) +
        f"\n\nCANDIDATE:\n{(profile_text or '')[:1500]}\n\nAnswer with one option or NONE:")
    try:
        reply = (llm(prompt) or "").strip()
    except Exception:
        return None
    low = reply.lower()
    if low in ("none", ""):
        return None
    for o in opts:                              # exact reply
        if o.strip().lower() == low:
            return o
    # the LLM may wrap the choice in a sentence; accept it iff EXACTLY ONE
    # option appears in the reply (ambiguous / none -> escalate, never guess).
    contained = [o for o in opts if o.strip().lower() in low]
    return contained[0] if len(contained) == 1 else None


def match_value_to_option(label, value, options, llm) -> str | None:
    """Rung 3 of value->option matching: we already HAVE the answer `value`
    (e.g. 'Male'); ask the llm which live option means the same (e.g. 'Man').
    Validates the reply against `options`; never returns a non-option."""
    opts = [o for o in (options or []) if o and o.strip()]
    if not opts:
        return None
    prompt = (
        f"Application question: \"{label}\"\n"
        f"The candidate's answer is: \"{value}\"\n"
        "Choose the ONE option below that expresses that same answer to this "
        "question. Reply with the option text EXACTLY as written, or NONE if none "
        "fit.\n\nOPTIONS:\n"
        + "\n".join(f"- {o}" for o in opts) + "\n\nAnswer with one option or NONE:")
    try:
        reply = (llm(prompt) or "").strip()
    except Exception:
        return None
    low = reply.lower()
    if low in ("none", ""):
        return None
    for o in opts:
        if o.strip().lower() == low:
            return o
    contained = [o for o in opts if o.strip().lower() in low]
    return contained[0] if len(contained) == 1 else None


from ..orchestrator.mapper import FillDecision, _action_for_kind

_SELECT_KINDS = {"select", "radio_group"}
# Not application questions — never draft an answer into these (search/nav boxes).
_NOT_A_QUESTION = re.compile(r"\bsearch\b|\bfilter\b|\bkeyword", re.I)


def judge(needs_human, ctx, llm, cap=6, orchestrator=None):
    """Answer the fields map_screen escalated. Returns (answered, still_need,
    flagged). Never raises; never answers a sensitive field; never exceeds `cap`
    model calls; option fields fill a real option or escalate."""
    try:
        from job_dashboard.apply.screening import draft_screening_answer
    except Exception:
        draft_screening_answer = None      # answerer unavailable -> free-text escalates
    answered, still_need, flagged = [], [], set()
    calls = 0
    hard = []                                  # weak free-text -> tier-3 orchestrator
    for f in needs_human:
        if _is_sensitive(f):
            still_need.append(f); continue
        if calls >= cap:
            still_need.append(f); continue
        if f.kind in _SELECT_KINDS:
            calls += 1
            opt = map_option(f.label, f.options, ctx.profile_text, llm)
            if opt is None:
                still_need.append(f)
            else:
                answered.append(FillDecision(f.ref, f.kind, f.label, opt,
                                             _action_for_kind(f.kind), "judgment"))
            continue
        if f.kind == "textarea":
            # Essays are personal — never auto-commit them. Escalate so the
            # collector can hand the human an editable draft to approve/edit.
            still_need.append(f); continue
        if f.kind == "text" and f.purpose is None:
            if _NOT_A_QUESTION.search(f.label or "") or draft_screening_answer is None:
                still_need.append(f); continue   # search box, or answerer unavailable
            calls += 1
            res = draft_screening_answer(ctx.job, f.label, ctx.profile_text,
                                         ctx.research, ctx.resume_text, llm=llm)
            weak = res.get("flags") or res.get("unsupported_company_claims")
            if weak and orchestrator is not None:
                hard.append(f); continue       # route the weak ones to tier-3
            answered.append(FillDecision(f.ref, f.kind, f.label, res["answer"], "fill", "judgment"))
            if weak:
                flagged.add(f.ref)
            continue
        still_need.append(f)                    # unhandled kind -> escalate
    if hard and orchestrator is not None:
        try:
            replies = orchestrator([{"ref": f.ref, "label": f.label,
                                     "job": ctx.job, "profile_text": ctx.profile_text}
                                    for f in hard]) or {}
        except Exception:
            replies = {}
        for f in hard:
            ans = replies.get(f.ref)
            if ans:
                answered.append(FillDecision(f.ref, f.kind, f.label, ans, "fill", "orchestrator"))
            else:
                still_need.append(f)
    return answered, still_need, flagged
