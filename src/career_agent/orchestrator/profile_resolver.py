"""Resolve a field purpose to a value from the CandidateProfile, using an index
for repeating experience/education rows."""
from __future__ import annotations

_EXP = {"employer": "company", "job_title": "title", "start_date": "start", "end_date": "end"}
_EDU = {"school": "school", "degree": "degree", "field_of_study": "field"}


def resolve(purpose, profile, index=0):
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
