"""Verifier: catch a draft that talks about a project whose material was not retrieved, and enforce a length limit."""
from __future__ import annotations

import re


def _terms(unit) -> set[str]:
    return ({str(unit.get("title", "")).lower(), *(t.lower() for t in unit.get("tech", [])),
             *(t.lower() for t in unit.get("tags", []))} - {""})


def distinct_terms(kb, pid) -> set[str]:
    """Terms (title, tech, tags) that belong to this project and to no other unit."""
    others: set[str] = set()
    for oid, unit in kb.units.items():
        if oid != pid:
            others |= _terms(unit)
    return {t for t in _terms(kb.units[pid]) - others if len(t) >= 3}


def leak_check(answer, chunks, kb) -> list[str]:
    used = {c.project_id for c in chunks if c.project_id}
    low = (answer or "").lower()
    leaks = []
    for unit in kb.projects():
        if unit["id"] in used:
            continue
        if any(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", low) for t in distinct_terms(kb, unit["id"])):
            leaks.append(unit["id"])
    return leaks


def fit_length(answer, limit) -> tuple[str, bool]:
    if not limit or len(answer) <= limit:
        return answer, False
    cut = answer[:limit]
    ends = [m.end() for m in re.finditer(r"[.!?](?:\s|$)", cut)]
    return (cut[:ends[-1]].strip() if ends else cut), True
