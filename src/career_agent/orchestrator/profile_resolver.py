"""Resolve a field purpose to a value from the CandidateProfile, using an index
for repeating experience/education rows."""
from __future__ import annotations

import re

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
# Strip a leading country-code prefix ("+91 ") from the stored phone value —
# the "phone number" field almost always sits next to its own country-code
# selector (Workday's 3-field block, intl-tel-input, etc.) and wants local
# digits only, not the full international string.
_PHONE_CC_RE = re.compile(r"^\+\d{1,3}[\s-]*")

_EXP = {"employer": "company", "job_title": "title", "start_date": "start", "end_date": "end"}
_EDU = {"school": "school", "degree": "degree", "field_of_study": "field"}
# Voluntary self-ID: purpose -> contact key. Filled from the user's provided
# values (never guessed); absent -> None (escalate).
_DEMO = {"gender": "gender", "ethnicity": "ethnicity",
         "veteran": "veteran_status", "disability": "disability_status"}
# ponytail: small India city->state lookup, covers the cities in this profile.
# Add more as they come up, or set profile.contact["state"] directly to skip it.
_INDIA_STATE_BY_CITY = {"mumbai": "Maharashtra", "bengaluru": "Karnataka",
                        "bangalore": "Karnataka"}


def _name_parts(contact):
    first, last = contact.get("first_name"), contact.get("last_name")
    if first or last:
        return (first or "", last or "")
    toks = (contact.get("full_name") or "").split()
    return (toks[0] if toks else "", " ".join(toks[1:]))


_DIAL_BY_COUNTRY = {"india": "+91", "united states": "+1", "usa": "+1", "us": "+1", "united kingdom": "+44",
                    "uk": "+44", "canada": "+1", "singapore": "+65", "united arab emirates": "+971", "uae": "+971",
                    "germany": "+49", "australia": "+61"}


def resolve(purpose, profile, index=0):
    if purpose in ("first_name", "last_name"):
        first, last = _name_parts(profile.contact)
        return (first if purpose == "first_name" else last) or None
    if purpose == "middle_name":
        return profile.contact.get("middle_name") or None   # escalate if absent
    if purpose in _DEMO:                                     # user-provided self-ID
        return profile.contact.get(_DEMO[purpose]) or None
    if purpose == "skill_years":
        return None          # no per-skill table: total experience would overclaim -> ask once
    if purpose == "current_ctc":
        return profile.contact.get("current_ctc") or None
    if purpose == "phone_country_code":
        m = _PHONE_CC_RE.match((profile.contact.get("phone") or "").strip())
        if m:
            return m.group(0).strip(" -")
        # no prefix on the number: the dial code of the country the profile says you live in (a fact, not a guess)
        country = (profile.contact.get("location") or "").split(",")[-1].strip().lower()
        return _DIAL_BY_COUNTRY.get(country)
    if purpose == "phone":
        raw = profile.contact.get("phone")
        return (_PHONE_CC_RE.sub("", raw).strip() or None) if raw else None
    if purpose == "city":
        loc = profile.contact.get("location") or ""
        return loc.split(",")[0].strip() or None if loc else None
    if purpose == "state":
        explicit = profile.contact.get("state")
        if explicit:
            return explicit
        city = (profile.contact.get("location") or "").split(",")[0].strip().lower()
        return _INDIA_STATE_BY_CITY.get(city)
    if purpose == "country":
        loc = profile.contact.get("location") or ""
        return loc.split(",")[-1].strip() if "," in loc else None
    if purpose in _EXP:
        if 0 <= index < len(profile.experiences):
            return getattr(profile.experiences[index], _EXP[purpose]) or None
        return None
    if purpose in _EDU:
        if 0 <= index < len(profile.education):
            return getattr(profile.education[index], _EDU[purpose]) or None
        return None
    if purpose == "graduation_year":
        if 0 <= index < len(profile.education):
            m = _YEAR_RE.search(profile.education[index].end or "")
            return m.group(0) if m else None
        return None
    if purpose == "skills":
        return ", ".join(profile.skills) if profile.skills else None
    return profile.contact.get(purpose) or None


# Degree LEVEL: a site's degree select offers levels ("Bachelor's Degree"), while the profile holds the degree as
# written ("B.Tech"). First pattern that matches wins, most specific first.
_DEGREE_LEVELS = (
    ("Post-Doctorate", re.compile(r"post-?\s?doc", re.I)),
    ("Doctorate", re.compile(r"\b(ph\.?\s?d|doctorate|doctoral|d\.?\s?phil)\b", re.I)),
    ("Master's Degree", re.compile(r"\b(m\.?\s?(tech|e|sc|s|a|com|ca|phil|pharm)|mba|mca|masters?)\b", re.I)),
    ("Bachelor's Degree", re.compile(r"\b(b\.?\s?(tech|e|sc|s|a|com|ca|pharm)|bba|bca|llb|bachelors?)\b", re.I)),
    ("Associate's Degree", re.compile(r"\b(associates?|aas|aa)\b", re.I)),
    ("Technical/Trade School", re.compile(r"\b(diploma|iti|polytechnic)\b", re.I)),
    ("High School Graduate or Equivalent", re.compile(r"\b(10th|12th|ssc|hsc|matric\w*|high school|secondary)\b", re.I)),
)
_LEVEL_RANK = [lvl for lvl, _ in reversed(_DEGREE_LEVELS)]    # low -> high
_K12_SCHOOL = re.compile(r"school|vidyalaya|montessori|high school|secondary|public school|convent", re.I)
_NOT_K12 = re.compile(r"university|institute|college|\biit\b|\bnit\b|\bbits\b", re.I)


def degree_level(degree: str) -> str | None:
    """The site's degree-level option for a profile degree ('B.Tech' -> "Bachelor's Degree"), or None."""
    for level, pat in _DEGREE_LEVELS:
        if pat.search(degree or ""):
            return level
    return None


def is_k12_school(school: str) -> bool:
    """A school-level name (Montessori, '... School') rather than a college: '... School' without a university word."""
    return bool(_K12_SCHOOL.search(school or "")) and not _NOT_K12.search(school or "")


def _school_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def highest_degree_level(profile) -> str | None:
    """The highest level across the profile's education ('Highest Degree/Diploma Obtained')."""
    ranked = [lvl for lvl in (degree_level(e.degree) for e in profile.education) if lvl]
    return max(ranked, key=_LEVEL_RANK.index) if ranked else None


_PARSER_PLACEHOLDER = re.compile(r"^\s*(not (provided|available|specified|found)( in (the )?(text|resume|cv))?|n/?a|none|"
                                 r"unknown|-+)\s*\.?\s*$", re.I)


def row_degree_level(profile, index: int, school_value: str | None) -> str | None:
    """Level for one repeated education row. The row's School text names the profile entry it is (fuzzy contains);
    a K-12 school with no profile match is High School; any other unmatched school -> None (never guessed).
    With no School text on the page, fall back to the profile entry at the same index."""
    school = (school_value or "").strip()
    if _PARSER_PLACEHOLDER.match(school):        # a résumé parser's "Not provided in text" names no school
        school = ""
    if not school:
        if 0 <= index < len(profile.education):
            return degree_level(profile.education[index].degree)
        return None
    key = _school_key(school)
    for e in profile.education:
        ek = _school_key(e.school)
        if key and ek and (key in ek or ek in key):
            return degree_level(e.degree)
    return "High School Graduate or Equivalent" if is_k12_school(school) else None
