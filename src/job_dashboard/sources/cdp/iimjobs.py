"""IIMJobs adapter. The search page is server-rendered and fires no list call, so the list and detail are
same-origin fetches to gladiator.iimjobs.com (header version: 2). Reads only; nothing is clicked."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import quote

from job_dashboard.models import JobListing
from job_dashboard.sources.cdp.types import CapReached, html_to_text

SITE = "iimjobs"
HOSTS = ("gladiator.iimjobs.com",)
API = "https://gladiator.iimjobs.com/job"
TERMS = ["data scientist", "ai engineer", "machine learning engineer", "llm engineer"]
POSTING = {24: 1, 72: 3, 168: 7, 720: 30}
_HDR = {"version": "2"}


def parse_search(body):
    cards = []
    for x in body.get("data") or []:
        company = ((x.get("companyData") or {}).get("companyName") or "").strip()
        if not x.get("id") or not x.get("title") or not company:
            continue
        cards.append(dict(
            id=str(x["id"]), title=x["title"], company=company,
            location=", ".join(l["name"] for l in x.get("locations") or [] if l.get("name")) or None,
            posted_ms=x.get("createdTimeMs"), url=x.get("jobDetailUrl") or f"https://www.iimjobs.com/j/x-{x['id']}",
            apply_url=x.get("applyUrl") or None))
    return cards, bool(body.get("hasMore"))


def to_listing(card, description) -> JobListing:
    ms = card.get("posted_ms")
    return JobListing(
        source=SITE, external_id=card["id"], title=card["title"], company=card["company"],
        location=card.get("location"), job_url=card["url"], description=description,
        posted_date=datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat() if ms else None,
        apply_url=card["apply_url"], apply_kind="external" if card["apply_url"] else "native")


def run(session, ctx):
    hours = 720 if ctx.mode == "backfill" else ctx.hours
    days = POSTING[next((b for b in sorted(POSTING) if b >= hours), max(POSTING))]   # round up to a supported window
    seen, todo, found = set(), [], []
    try:
        session.goto("https://www.iimjobs.com/k/data-scientist-jobs")
        for term in ctx.terms:
            for pg in range(ctx.max_pages):
                body = json.loads(session.fetch(
                    f"{API}/search?query={quote(term)}&page={pg}&posting={days}", hosts=HOSTS, headers=_HDR))
                cards, more = parse_search(body)
                if not cards and not more:
                    break
                ctx.stats["pages"] += 1
                for c in cards:
                    if c["id"] in seen:
                        continue
                    seen.add(c["id"])
                    if ctx.known(c["id"], c["url"]):
                        ctx.stats["skipped_known"] += 1
                    else:
                        todo.append(c)
                if not more:
                    break
        for c in todo:
            data = json.loads(session.fetch(f"{API}/detail?jobcode={c['id']}", hosts=HOSTS, headers=_HDR)).get("data") or {}
            text = html_to_text(data.get("introText") or "")
            if text:
                found.append(to_listing(c, text))
    except CapReached:
        ctx.stats["capped"] = True
    return found
