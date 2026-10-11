"""Verifier: catch a draft that talks about a project whose material was not retrieved, and enforce a length limit."""
from __future__ import annotations

import re


def _terms(unit) -> set[str]:
    # title + tech only: tags are generic words ("real-time", "production", "fraud") that any answer may use
    return ({str(unit.get("title", "")).lower(), *(t.lower() for t in unit.get("tech", []))} - {""})


def distinct_terms(kb, pid) -> set[str]:
    """Terms (title, tech) that belong to this project and to no other unit."""
    others: set[str] = set()
    for oid, unit in kb.units.items():
        if oid != pid:
            others |= _terms(unit)
    return {t for t in _terms(kb.units[pid]) - others if len(t) >= 3}


def leak_check(answer, chunks, kb) -> list[str]:
    used = {c.project_id for c in chunks if c.project_id}
    low = (answer or "").lower()
    seen = " ".join(c.text for c in chunks).lower()     # a term that is in the retrieved material is not a leak
    leaks = []
    for unit in kb.projects():
        if unit["id"] in used:
            continue
        def hit(t, text):
            return re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", text)
        if any(hit(t, low) and not hit(t, seen) for t in distinct_terms(kb, unit["id"])):
            leaks.append(unit["id"])
    return leaks


_PROJECT_NAME = re.compile(
    r"(?:\bin (?:the|my)|\bon (?:the|my)|\bat (?:the|my)|\bthe|\bmy)\s+['\"“‘]?([A-Z][\w&.-]*(?: [A-Z0-9][\w&.-]*){0,4})['\"”’]?\s+(?:project|system|platform|pipeline|app|chatbot)\b"
    r"|\bproject\s+(?:called|named)\s+['\"“‘]?([A-Z][\w&.-]*(?: [A-Z0-9][\w&.-]*){0,4})['\"”’]?"
    r"|['\"“‘]([A-Z][\w&.-]*(?: [A-Z0-9][\w&.-]*){0,4})['\"”’]\s+project")


def invented_projects(answer, chunks) -> list[str]:
    """Names the answer gives to a project that appear nowhere in the material it was given (the writer made them up)."""
    seen = " ".join(c.text for c in chunks).lower()
    out = []
    for m in _PROJECT_NAME.finditer(answer or ""):
        name = next(g for g in m.groups() if g)
        if name.lower() not in seen and name not in out:
            out.append(name)
    return out


def fit_length(answer, limit) -> tuple[str, bool]:
    if not limit or len(answer) <= limit:
        return answer, False
    cut = answer[:limit]
    ends = [m.end() for m in re.finditer(r"[.!?](?:\s|$)", cut)]
    return (cut[:ends[-1]].strip() if ends else cut), True
