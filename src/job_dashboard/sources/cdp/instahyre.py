"""Instahyre adapter: page 1 of each term arrives by the page's own job_search call; deeper pages and
job details are same-origin fetches. No clicks, never touches Apply/Interested."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from job_dashboard.models import JobListing
from job_dashboard.sources.cdp.types import CapReached, html_to_text

SITE = "instahyre"
HOSTS = ("www.instahyre.com",)
TERMS = ["machine learning engineer", "data scientist", "ai engineer", "llm engineer"]
RETENTION_DAYS = 30
_LD = re.compile(r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', re.S)
_DATE = re.compile(r'"datePosted":\s*"([^"]+)"')


def _list_path(term, offset):
    return (f"https://www.instahyre.com/api/v1/job_search?company_size=0&isLandingPage=true&job_type=0&offset={offset}"
            f"&skills={quote(term)}")


def parse_list(body):
    cards = []
    for o in body.get("objects") or []:
        emp = o.get("employer") or {}
        if not o.get("id") or not o.get("title") or not emp.get("company_name"):
            continue
        cards.append(dict(id=int(o["id"]), title=o["title"], company=emp["company_name"],
                          location=o.get("locations"), url=(o.get("public_url") or "").split("?")[0]
                          or f"https://www.instahyre.com/job-{o['id']}-x/"))
    return cards, (body.get("meta") or {}).get("total_count")


def parse_detail(html):
    m = _DATE.search(html or "")
    try:
        posted = date.fromisoformat(m.group(1)[:10]) if m else None
    except ValueError:
        posted = None
    desc = ""
    for blob in _LD.findall(html or ""):
        try:
            j = json.loads(blob)
        except ValueError:
            continue
        if j.get("@type") == "JobPosting":
            desc = html_to_text(j.get("description") or "")
            break
    return {"date": posted, "description": desc}


def to_listing(card, detail) -> JobListing:
    d = detail["date"]
    return JobListing(
        source=SITE, external_id=str(card["id"]), title=card["title"], company=card["company"],
        location=card.get("location"), job_url=card["url"], description=detail["description"],
        posted_date=datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat() if d else None,
        apply_kind="native")


def run(session, ctx, today=None):
    from job_dashboard.match.relevance import is_target_role
    today = today or date.today()
    cutoff = today - timedelta(days=RETENTION_DAYS)
    cands, found, off = {}, [], set()
    ctx.partial = found                  # salvaged by the runner if this run dies midway
    ctx.stats.setdefault("skipped_stale", 0)
    ctx.stats.setdefault("off_target", 0)
    try:
        for term in ctx.terms:
            for _ in range(2):                      # the page's own call can be missed: reload once
                with session.capture("api/v1/job_search") as cap:
                    session.goto(f"https://www.instahyre.com/search-jobs?skills={quote(term)}")
                first = [c for _, b in cap.bodies() for c in parse_list(b)[0]]
                if first:
                    break
            for p in range(1, ctx.max_pages + 1):
                cards = first if p == 1 else parse_list(json.loads(
                    session.fetch(_list_path(term, 20 * (p - 1)), hosts=HOSTS)))[0]
                if not cards:
                    break
                ctx.stats["pages"] += 1
                for c in cards:
                    if is_target_role(c["title"]):
                        cands[c["id"]] = c
                    elif c["id"] not in cands and c["id"] not in off:
                        off.add(c["id"])
                        ctx.stats["off_target"] += 1
        streak = []                                 # consecutive stale ids; one stale outlier must not move the anchor
        for cid in sorted(cands, reverse=True):
            c = cands[cid]
            if ctx.known(str(cid), c["url"]):
                ctx.stats["skipped_known"] += 1
                continue
            if cid <= ctx.anchor:
                ctx.stats["skipped_stale"] += 1
                continue
            detail = parse_detail(session.fetch(f"https://www.instahyre.com/job-{cid}-x/", hosts=HOSTS))
            if detail["date"] is None:                # retention unverifiable: don't insert, don't mark known
                ctx.stats["undated"] = ctx.stats.get("undated", 0) + 1
                continue
            if detail["date"] < cutoff:
                streak.append(cid)
                if len(streak) >= 3:
                    ctx.anchor = max(ctx.anchor, streak[0])
                    if ctx.save_anchor:
                        ctx.save_anchor(ctx.anchor)
                continue
            streak = []
            if detail["description"]:
                found.append(to_listing(c, detail))
    except CapReached:
        ctx.stats["capped"] = True
    return found
