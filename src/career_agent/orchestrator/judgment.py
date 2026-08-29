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
    for o in opts:
        if o.strip().lower() == low:
            return o
    return None
