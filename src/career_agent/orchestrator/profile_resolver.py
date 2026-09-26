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


def resolve(purpose, profile, index=0):
    if purpose in ("first_name", "last_name"):
        first, last = _name_parts(profile.contact)
        return (first if purpose == "first_name" else last) or None
    if purpose == "middle_name":
        return profile.contact.get("middle_name") or None   # escalate if absent
    if purpose in _DEMO:                                     # user-provided self-ID
        return profile.contact.get(_DEMO[purpose]) or None
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
