"""CandidateProfile: structured facts extracted from a saved résumé version
(resume_layouts blocks) + application_profile. Rule-based; a `split` callable
(qwen3:14b) is used only for role-header titles a rule can't parse."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Experience:
    company: str
    title: str = ""
    start: str = ""
    end: str = ""
    bullets: list = field(default_factory=list)


@dataclass
class Education:
    school: str
    degree: str = ""
    field: str = ""
    start: str = ""
    end: str = ""


@dataclass
class CandidateProfile:
    contact: dict = field(default_factory=dict)
    experiences: list = field(default_factory=list)
    education: list = field(default_factory=list)
    skills: list = field(default_factory=list)


# "Role, Company — start – end, location"  (em dash before dates; en dash in range)
_ROLE_RE = re.compile(
    r"^(?P<title>[^,]+?),\s*(?P<company>.+?)\s*(?:—|--|-)\s*"
    r"(?P<start>.+?)\s*[–\-]\s*(?P<end>[^,]+)", re.U)


def _rule_split(title: str) -> dict:
    m = _ROLE_RE.match(title.strip())
    if not m:
        return {}
    return {k: m.group(k).strip() for k in ("title", "company", "start", "end")}


def _skills_from(bullet: str) -> list:
    # "**Programming**: Python, SQL, AWS" -> [Python, SQL, AWS]
    tail = bullet.split(":", 1)[1] if ":" in bullet else bullet
    return [s.strip(" *") for s in re.split(r"[,;]", tail) if s.strip(" *")]


_EDU_PREFIX_RE = re.compile(r"^\s*education\s*:\s*", re.I)


def _parse_education(title: str) -> "Education":
    # "Education: B.Tech, IIT (BHU) Varanasi"  or  "...— 2018 – 2022" when dated.
    t = _EDU_PREFIX_RE.sub("", title or "").strip()
    parts = _rule_split(t)                       # "Degree, School — start – end"
    if parts:
        return Education(school=parts["company"], degree=parts["title"],
                         start=parts["start"], end=parts["end"])
    if "," in t:                                 # "Degree, School" (no dates)
        degree, school = t.split(",", 1)
        return Education(school=school.strip(), degree=degree.strip())
    return Education(school=t)                    # bare school name


def education_from_segments(segments) -> list:
    """Education lives in the fixed segment library (segments.yaml), prepended
    at render time — NOT in the saved layout blocks — so it is pulled from the
    segments separately from the experience/skills blocks."""
    return [_parse_education(s.title)
            for s in segments if getattr(s, "kind", None) == "education"]


def blocks_to_profile(blocks, contact, split=None) -> CandidateProfile:
    split = split or _rule_split
    prof = CandidateProfile(contact=dict(contact or {}))
    by_company: dict = {}
    for b in blocks:
        if b.get("excluded"):
            continue
        kind = b.get("kind")
        if kind == "skills":
            for bl in b.get("bullets", []):
                prof.skills.extend(_skills_from(bl))
        elif kind == "experience":
            company = b.get("group") or "(unknown)"
            exp = by_company.get(company)
            if exp is None:
                exp = Experience(company=company)
                by_company[company] = exp
                prof.experiences.append(exp)
            if b.get("roleHeader"):
                parts = split(b.get("title", ""))
                if parts:
                    exp.title = parts.get("title", exp.title)
                    exp.company = parts.get("company", exp.company)
                    exp.start = parts.get("start", exp.start)
                    exp.end = parts.get("end", exp.end)
            # collect bullets from ANY block (a roleHeader can carry them too,
            # e.g. an internship with no separate description blocks).
            exp.bullets.extend(b.get("bullets", []))
    # de-dup skills, preserve order
    seen = set()
    prof.skills = [s for s in prof.skills if not (s in seen or seen.add(s))]
    return prof


def load_candidate_profile(conn, version="Rakshit_Singh_draft1", contact=None, split=None):
    from job_dashboard.db import get_resume_layout
    layout = get_resume_layout(conn, version)
    blocks = (layout or {}).get("layout", [])
    prof = blocks_to_profile(blocks, contact or {}, split=split)
    try:
        from job_dashboard.resume.segments import load_segments
        prof.education = education_from_segments(load_segments())
    except Exception:
        pass   # segment library unavailable -> no education, the walk still runs
    return prof
