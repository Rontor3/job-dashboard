"""The compact Form Model: structured fields extracted from a page, plus a
rule-based purpose guesser. Pure — no browser, no LLM."""
from __future__ import annotations

import re
from dataclasses import dataclass, field as _field

KNOWN_PURPOSES = frozenset({
    "full_name", "first_name", "last_name", "middle_name", "email", "phone",
    "location", "city", "country", "veteran", "gender", "ethnicity", "disability",
    "linkedin_url", "github_url", "twitter_url", "facebook_url",
    "portfolio_url", "work_authorization", "visa_sponsorship", "prior_contact",
    "conflict_of_interest",
    "years_experience",
    "notice_period", "salary_expectation", "willing_to_relocate",
    "attestation", "resume_upload", "phone_type", "referral_source",
    "employer", "job_title", "start_date", "end_date", "degree", "school",
    "field_of_study", "gpa", "skills", "summary",
    "motivation",   # cover-letter / interest blurb (SR hiring manager message)
    "file_comment", # short description field next to file upload (e.g. Taleo "Comments about the file")
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
    description: str = ""      # accessible description (aria-describedby helper text)


# Ordered most-specific-first; first hit wins.
_RULES: list[tuple[str, str]] = [
    # "Let the company know about your interest" must NOT hit the employer rule
    # (which would fill it with the company name). Match it early as motivation
    # so judgment tier writes a proper cover-letter blurb instead.
    (r"\binterest (working|joining|in this)\b|\blet.{1,20}know about your interest\b"
     r"|\bmessage to (the )?(hiring|recruiter|team)\b|\bhiring manager message\b", "motivation"),
    # Sponsorship/work-auth must precede employer — "require employer sponsorship"
    # contains \bemployer\b and would otherwise be misclassified as a company-name field.
    (r"\bsponsor(ship)?\b", "visa_sponsorship"),
    # Résumé-driven (employer/job/education) purposes. `employer` must precede
    # `full_name` — "Company Name" contains "name" and must not hit full_name.
    (r"\bemployer\b|\bcompany name\b|\bcompany\b|\borganization\b", "employer"),
    (r"\bfirst name\b|\bgiven name\b|\bforename\b", "first_name"),
    (r"\blast name\b|\bsurname\b|\bfamily name\b", "last_name"),
    (r"\bmiddle\b", "middle_name"),        # "Middle", "Middle Name", "Middle Initial"
    (r"\bfull name\b|\byour name\b|\bname\b", "full_name"),
    # Bare "role" over-matched "for this role" (relocation/interview questions);
    # require a title-like word instead. "Position" still catches job-title inputs.
    (r"\bjob title\b|\bposition title\b|\bposition\b|\brole title\b|\btitle\b", "job_title"),
    (r"\bstart date\b|\bdate from\b|\bfrom date\b", "start_date"),
    (r"\bend date\b|\bdate to\b|\bto date\b", "end_date"),
    (r"\bfield of study\b|\bmajor\b|\bspecial", "field_of_study"),
    (r"\bdegree\b|\bqualification\b", "degree"),
    (r"\buniversity\b|\bschool\b|\bcollege\b|\binstitution\b", "school"),
    (r"\bgpa\b|\bgrade\b|\bcgpa\b|\bpercentage\b", "gpa"),
    (r"\bskills?\b|\bkey skills\b|\btechnolog", "skills"),
    (r"\bsummary\b|\babout you\b|\bprofile summary\b", "summary"),
    (r"\be-?mail\b", "email"),
    (r"\bphone (device|type)\b|\bphone_type\b", "phone_type"),
    (r"\bphone\b|\bmobile\b|\bcontact number\b", "phone"),
    (r"^\s*source\s*\*?\s*$", "referral_source"),  # Phenom applicantSource: label is literally "Source*"
    (r"\bhear about us\b|\bhear about (this|the) (job|role|position|opening)\b"
     r"|\bhow did you (find|learn about|discover)\b|\bjob source\b", "referral_source"),
    (r"\blinkedin\b", "linkedin_url"),
    (r"\bfacebook\b|\bfb\.com\b", "facebook_url"),
    (r"\bgithub\b", "github_url"),
    (r"\btwitter\b|\bx\.com\b", "twitter_url"),
    (r"\bportfolio\b|\bwebsite\b|\bpersonal site\b", "portfolio_url"),
    (r"\bsponsor", "visa_sponsorship"),
    (r"\bapplied before\b|\bpreviously applied\b|\bapply (to|with) (this|our)\b", "prior_contact"),
    (r"\brelativ|\bknow (anyone|someone)\b|\breferr|\bemployee referral\b"
     r"|\b(contact|connection|relationship)s? (at|with|to)\b|\bfriends? (at|who)\b", "prior_contact"),
    (r"\bconflict.of.interest\b|\bcommercial or government contracts?\b|\banti.corruption\b", "conflict_of_interest"),
    (r"\bauthoriz|\bwork permit\b|\bvisa\b|\beligible to work\b|\blegally (authorized|entitled)\b", "work_authorization"),
    (r"\byears? of experience\b|\byears? experience\b|\bexperience\b", "years_experience"),
    (r"\bnotice period\b|\bavailab|\bearliest start\b|\bstart date\b", "notice_period"),
    (r"\bsalary\b|\bcompensation\b|\bexpected ctc\b|\bpay expectation\b", "salary_expectation"),
    # An address field can *mention* relocation ("...type 'relocating'") but is a
    # free-text address, not a yes/no — must precede the relocate rule. Escalates
    # (no street address in the profile), never fills "Yes". `email` above wins for
    # "Email Address".
    (r"\baddress\b", "address"),
    (r"\bwilling to relocat|\bopen to relocat|\brelocat\w*\s*\?|\brelocat", "willing_to_relocate"),
    (r"\bcomments? about (the )?file\b|\bfile (comment|description)\b", "file_comment"),
    (r"\bresume\b|\bcv\b|\bupload.*(resume|cv)\b", "resume_upload"),
    (r"\barmed forces\b|\bmilitary\b|\bveteran\b|\breserve component\b"
     r"|\bserved (as|in)\b", "veteran"),
    (r"\bdisab", "disability"),
    (r"\bethnic|\brace\b|\bhispanic\b|\blatino\b", "ethnicity"),
    (r"\bgender\b", "gender"),
    (r"\bcountry\b", "country"),
    (r"\bcity\b|\btown\b", "city"),
    (r"\blocation\b", "location"),
    # Auth-wall fields — credential_provider handles these; rule-filler must skip them.
    (r"\bverify\b.*\bpassword\b|\bpassword\b.*\bverify\b|\bconfirm\b.*\bpassword\b", "password_confirm"),
    (r"\bnew password\b|\bcreate password\b|\bset password\b", "password_new"),
    (r"\bpassword\b", "password"),
]

_RESUME_RE = re.compile(r"\bresume\b|\bcv\b", re.I)

_ATTEST = re.compile(
    r"\bi (certify|agree|consent|acknowledge|authorize)\b|\bbackground check\b"
    r"|\bterms\b|\bprivacy policy\b|\btrue and (complete|correct)\b",
    re.I,
)


# Purposes that resolve to a TEXT value to type — nonsensical on a checkbox
# ("Use name only" must not become full_name).
_TEXT_VALUE_PURPOSES = {
    "first_name", "last_name", "middle_name", "full_name", "email", "phone",
    "linkedin_url", "github_url", "portfolio_url", "employer", "job_title",
    "start_date", "end_date", "field_of_study", "degree", "school", "gpa",
    "skills", "summary", "address", "city", "location", "country",
    "years_experience", "notice_period", "salary_expectation",
}


def guess_purpose(label: str, kind: str) -> str | None:
    text = (label or "").strip().lower()
    if not text:
        return None
    if kind == "file":
        return "resume_upload" if _RESUME_RE.search(text) else None
    if kind == "checkbox":
        if _ATTEST.search(text):
            return "attestation"
        for pattern, purpose in _RULES:      # keep only question purposes, not text ones
            if re.search(pattern, text):
                return None if purpose in _TEXT_VALUE_PURPOSES else purpose
        return None
    for pattern, purpose in _RULES:
        if re.search(pattern, text):
            return purpose
    return None
