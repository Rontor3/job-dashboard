"""The compact Form Model: structured fields extracted from a page, plus a
rule-based purpose guesser. Pure — no browser, no LLM."""
from __future__ import annotations

import re
from dataclasses import dataclass, field as _field

KNOWN_PURPOSES = frozenset({
    "full_name", "first_name", "last_name", "email", "phone", "location",
    "country", "linkedin_url", "github_url",
    "portfolio_url", "work_authorization", "visa_sponsorship", "prior_contact",
    "years_experience",
    "notice_period", "salary_expectation", "willing_to_relocate",
    "attestation", "resume_upload",
    "employer", "job_title", "start_date", "end_date", "degree", "school",
    "field_of_study", "gpa", "skills", "summary",
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
    # Résumé-driven (employer/job/education) purposes. `employer` must precede
    # `full_name` — "Company Name" contains "name" and must not hit full_name.
    (r"\bemployer\b|\bcompany name\b|\bcompany\b|\borganization\b", "employer"),
    (r"\bfirst name\b|\bgiven name\b|\bforename\b", "first_name"),
    (r"\blast name\b|\bsurname\b|\bfamily name\b", "last_name"),
    (r"\bfull name\b|\byour name\b|\bname\b", "full_name"),
    (r"\bjob title\b|\bposition title\b|\brole\b|\btitle\b", "job_title"),
    (r"\bstart date\b|\bdate from\b|\bfrom date\b", "start_date"),
    (r"\bend date\b|\bdate to\b|\bto date\b", "end_date"),
    (r"\bfield of study\b|\bmajor\b|\bspecial", "field_of_study"),
    (r"\bdegree\b|\bqualification\b", "degree"),
    (r"\buniversity\b|\bschool\b|\bcollege\b|\binstitution\b", "school"),
    (r"\bgpa\b|\bgrade\b|\bcgpa\b|\bpercentage\b", "gpa"),
    (r"\bskills?\b|\bkey skills\b|\btechnolog", "skills"),
    (r"\bsummary\b|\babout you\b|\bprofile summary\b", "summary"),
    (r"\be-?mail\b", "email"),
    (r"\bphone\b|\bmobile\b|\bcontact number\b", "phone"),
    (r"\blinkedin\b", "linkedin_url"),
    (r"\bgithub\b", "github_url"),
    (r"\bportfolio\b|\bwebsite\b|\bpersonal site\b", "portfolio_url"),
    (r"\bsponsor", "visa_sponsorship"),
    (r"\brelativ|\bknow (anyone|someone)\b|\breferr|\bemployee referral\b"
     r"|\b(contact|connection|relationship)s? (at|with|to)\b|\bfriends? (at|who)\b", "prior_contact"),
    (r"\bauthoriz|\bwork permit\b|\bvisa\b|\beligible to work\b|\blegally (authorized|entitled)\b", "work_authorization"),
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
