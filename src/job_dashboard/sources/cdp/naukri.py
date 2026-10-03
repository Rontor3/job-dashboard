"""Naukri adapter. Reads only the responses Naukri's own pages make (jobapi/v3/search on a search
page, jobapi/v4/job/<id> on a job page). Never replays an API call, never clicks."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from job_dashboard.models import JobListing
from job_dashboard.sources.cdp.types import Blocked, CapReached, html_to_text, norm_text

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


_BLOCK = (403, 406, 429)


def _captured(session, url, needle):
    with session.capture(needle) as cap:
        session.goto(url)
    if any(getattr(r, "status", 200) in _BLOCK for r in cap.responses):
        raise Blocked(f"HTTP block on {needle}")
    return list(cap.bodies())


def _search(session, url):
    bodies = _captured(session, url, "jobapi/v3/search")
    if not bodies:                                   # cold load sometimes fires nothing: reload once
        bodies = _captured(session, url, "jobapi/v3/search")
    cards = []
    for _, b in bodies:
        cards.extend(parse_search(b)[0])
    return cards


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def run(session, ctx):
    from job_dashboard.match.relevance import is_target_role
    hours = 720 if ctx.mode == "backfill" else ctx.hours
    ctx.stats.setdefault("off_target", 0)
    seen_ids, seen_text, pending, found = set(), set(), {}, {}
    ctx.partial = found                  # salvaged by the runner if this run dies midway
    ctx.stats.setdefault("collapsed", 0)
    try:
        for term in ctx.terms:
            queue = pending.setdefault(term, [])
            for p in range(1, ctx.max_pages + 1):
                cards = _search(session, search_url(term, hours, p))
                if not cards:
                    break
                ctx.stats["pages"] += 1
                for c in cards:
                    if c["id"] in seen_ids or not c["company"]:
                        continue
                    seen_ids.add(c["id"])
                    if not is_target_role(c["title"]):
                        ctx.stats["off_target"] += 1
                        continue
                    url = job_url(c["jd_url"])
                    if ctx.known(c["id"], url):
                        ctx.stats["skipped_known"] += 1
                        if ctx.redate and c.get("posted_ms") and ctx.redate(c["id"], url, _iso(c["posted_ms"])):
                            ctx.stats["redated"] = ctx.stats.get("redated", 0) + 1
                        continue
                    key = collapse_key(c)
                    if key in seen_text or (ctx.known_text and ctx.known_text(c["title"], c["company"], c["location"] or "")):
                        ctx.stats["collapsed"] += 1
                        continue
                    seen_text.add(key)
                    queue.append(c)
        queues = [q for q in pending.values() if q]
        while queues:
            for q in list(queues):
                c = q.pop(0)
                for _, body in _captured(session, job_url(c["jd_url"]), "jobapi/v4/job/"):
                    d = parse_detail(body)
                    if d and d["job_id"] == c["id"]:
                        found[c["id"]] = to_listing(c, d["description"])
                if not q:
                    queues.remove(q)
    except CapReached:
        ctx.stats["capped"] = True
    return list(found.values())
