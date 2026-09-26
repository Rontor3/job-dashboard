"""Naukri adapter. Reads only the responses Naukri's own pages make (jobapi/v3/search on a search
page, jobapi/v4/job/<id> on a job page). Never replays an API call, never clicks."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from job_dashboard.models import JobListing
from job_dashboard.sources.cdp.types import html_to_text, norm_text

SITE = "naukri"
BASE = "https://www.naukri.com"
TERMS = ["machine learning engineer", "data scientist", "ai engineer", "llm engineer"]
AGES = {24: 1, 72: 3, 168: 7, 360: 15, 720: 30}       # window hours -> jobAge days


def search_url(term: str, hours: int, page: int = 1) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")
    return f"{BASE}/{slug}-jobs{'' if page == 1 else f'-{page}'}?jobAge={AGES[hours]}"


def _label(card, kind):
    return next((p.get("label") for p in card.get("placeholders") or [] if p.get("type") == kind), None)


def parse_search(body):
    out = []
    for d in body.get("jobDetails") or []:
        if not d.get("jobId") or not d.get("title") or not d.get("jdURL"):
            continue
        salary = _label(d, "salary")
        ext = bool(d.get("companyApplyJob"))
        out.append(dict(
            id=str(d["jobId"]), title=d["title"], company=d.get("companyName") or "",
            location=_label(d, "location"), salary=None if not salary or salary.lower() == "not disclosed" else salary,
            posted_ms=d.get("createdDate"), jd_url=d["jdURL"].split("?")[0], external=ext,
            apply_url=d.get("applyRedirectUrl") if ext else None, snippet=d.get("jobDescription") or ""))
    return out, body.get("noOfJobs")


def parse_detail(body):
    d = body.get("jobDetails")
    if not isinstance(d, dict) or not d.get("description") or not d.get("jobId"):
        return None
    return {"job_id": str(d["jobId"]), "description": html_to_text(d["description"])}


def collapse_key(card) -> str:
    return "|".join(norm_text(card.get(k)) for k in ("title", "company", "location"))


def job_url(jd_url: str) -> str:
    return BASE + jd_url


def to_listing(card, description) -> JobListing:
    ms = card.get("posted_ms")
    return JobListing(
        source=SITE, external_id=card["id"], title=card["title"], company=card["company"],
        location=card.get("location"), job_url=job_url(card["jd_url"]), description=description,
        salary_text=card.get("salary"),
        posted_date=datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat() if ms else None,
        apply_url=card.get("apply_url"), apply_kind="external" if card.get("external") and card.get("apply_url") else
        ("unknown" if card.get("external") else "native"))
