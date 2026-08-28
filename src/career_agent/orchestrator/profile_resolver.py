"""Resolve a field purpose to a value from the CandidateProfile, using an index
for repeating experience/education rows."""
from __future__ import annotations

_EXP = {"employer": "company", "job_title": "title", "start_date": "start", "end_date": "end"}
_EDU = {"school": "school", "degree": "degree", "field_of_study": "field"}


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
    if purpose == "veteran":
        return None                                          # never auto-answered
    if purpose == "city":
        loc = profile.contact.get("location") or ""
        return loc.split(",")[0].strip() or None if loc else None
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
    if purpose == "skills":
        return ", ".join(profile.skills) if profile.skills else None
    return profile.contact.get(purpose) or None
