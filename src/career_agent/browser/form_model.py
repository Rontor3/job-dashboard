"""The compact Form Model: structured fields extracted from a page, plus a
rule-based purpose guesser. Pure — no browser, no LLM."""
from __future__ import annotations

import re
from dataclasses import dataclass, field as _field

KNOWN_PURPOSES = frozenset({
    "full_name", "email", "phone", "location", "linkedin_url", "github_url",
    "portfolio_url", "work_authorization", "years_experience",
    "notice_period", "salary_expectation", "willing_to_relocate",
    "attestation", "resume_upload",
})


@dataclass(frozen=True)
class Field:
    ref: str
    kind: str
    label: str
    required: bool
    options: list = _field(default_factory=list)
    group: str | None = None
    purpose: str | None = None


# Ordered most-specific-first; first hit wins.
_RULES: list[tuple[str, str]] = [
    (r"\bfirst name\b|\blast name\b|\bfull name\b|\byour name\b|\bname\b", "full_name"),
    (r"\be-?mail\b", "email"),
    (r"\bphone\b|\bmobile\b|\bcontact number\b", "phone"),
    (r"\blinkedin\b", "linkedin_url"),
    (r"\bgithub\b", "github_url"),
    (r"\bportfolio\b|\bwebsite\b|\bpersonal site\b", "portfolio_url"),
    (r"\bauthoriz|\bwork permit\b|\bvisa\b|\bsponsor|\beligible to work\b", "work_authorization"),
    (r"\byears? of experience\b|\byears? experience\b|\bexperience\b", "years_experience"),
    (r"\bnotice period\b|\bavailab|\bearliest start\b|\bstart date\b", "notice_period"),
    (r"\bsalary\b|\bcompensation\b|\bexpected ctc\b|\bpay expectation\b", "salary_expectation"),
    (r"\brelocat", "willing_to_relocate"),
    (r"\bresume\b|\bcv\b|\bupload.*(resume|cv)\b", "resume_upload"),
    (r"\bcity\b|\blocation\b|\baddress\b", "location"),
]

_RESUME_RE = re.compile(r"\bresume\b|\bcv\b", re.I)

_ATTEST = re.compile(
    r"\bi (certify|agree|consent|acknowledge|authorize)\b|\bbackground check\b"
    r"|\bterms\b|\bprivacy policy\b|\btrue and (complete|correct)\b",
    re.I,
)


def guess_purpose(label: str, kind: str) -> str | None:
    text = (label or "").strip().lower()
    if not text:
        return None
    if kind == "file":
        return "resume_upload" if _RESUME_RE.search(text) else None
    if kind == "checkbox" and _ATTEST.search(text):
        return "attestation"
    for pattern, purpose in _RULES:
        if re.search(pattern, text):
            return purpose
    return None
