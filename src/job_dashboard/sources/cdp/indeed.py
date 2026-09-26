"""Indeed adapter (India + Remote). Reads only the documents Indeed's own pages load: the search page embeds
the job cards as window.mosaic JSON, a job page embeds a JSON-LD JobPosting. No API replay, no clicks.
Any Cloudflare/Turnstile challenge is a hard stop (Blocked), never solved or retried."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

from job_dashboard.models import JobListing
from job_dashboard.sources.cdp.types import Blocked, CapReached, html_to_text

SITE = "indeed"
BASE = "https://in.indeed.com"
TERMS = ["machine learning engineer", "ai engineer", "data scientist", "llm engineer", "mlops engineer"]
LOCATIONS = ("India", "Remote")

_MOSAIC = re.compile(r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.*?\});\s*\n', re.S)
_LD = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
_CHALLENGE = re.compile(r"<title>\s*Just a moment|challenge-platform|cf-turnstile", re.I)


def search_url(term: str, location: str, page: int) -> str:
    return f"{BASE}/jobs?q={quote_plus(term)}&l={quote_plus(location)}&sort=date&start={10 * page}"


def job_url(job_id: str) -> str:
    return f"{BASE}/viewjob?jk={job_id}"


def is_challenge(html: str) -> bool:
    return bool(_CHALLENGE.search(html or ""))


def parse_search(html: str) -> list:
    m = _MOSAIC.search(html or "")
    try:
        results = json.loads(m.group(1))["metaData"]["mosaicProviderJobCardsModel"]["results"] if m else []
    except (ValueError, KeyError, TypeError):
        return []
    return [dict(id=str(r["jobkey"]), title=r["title"], company=r["company"], location=r.get("formattedLocation"),
                 pub_ms=r.get("pubDate"), sponsored=bool(r.get("sponsored")), native=bool(r.get("indeedApplyable")))
            for r in results if isinstance(r, dict) and r.get("jobkey") and r.get("title") and r.get("company")]


def parse_detail(html: str):
    for raw in _LD.findall(html or ""):
        try:
            ld = json.loads(raw)
        except ValueError:
            continue
        if isinstance(ld, dict) and ld.get("@type") == "JobPosting" and ld.get("description"):
            return {"description": html_to_text(ld["description"]), "posted": ld.get("datePosted"),
                    "direct": bool(ld.get("directApply"))}
    return None


def to_listing(card, detail) -> JobListing:
    ms = card.get("pub_ms")
    return JobListing(
        source=SITE, external_id=card["id"], title=card["title"], company=card["company"],
        location=card.get("location"), job_url=job_url(card["id"]), description=detail["description"],
        posted_date=datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat() if ms else detail.get("posted"),
        apply_url=None, apply_kind="native" if card.get("native") or detail.get("direct") else "external")


def _captured(session, url, needle):
    """Documents the page itself loaded; a challenge anywhere is a hard stop."""
    with session.capture(needle) as cap:
        session.goto(url)
    docs = [(u, t) for u, _, t in cap.texts()]
    if any(is_challenge(t) for _, t in docs):
        raise Blocked("challenge")
    return docs


def run(session, ctx):
    from job_dashboard.match.relevance import is_target_role
    hours = 720 if ctx.mode == "backfill" else ctx.hours
    cutoff = time.time() - hours * 3600
    seen, pending, found = set(), {}, {}
    ctx.stats.setdefault("off_target", 0)
    try:
        for term in ctx.terms:
            for loc in LOCATIONS:
                queue, stale = pending.setdefault((term, loc), []), 0
                for p in range(ctx.max_pages):
                    cards = [c for _, t in _captured(session, search_url(term, loc, p), f"{BASE[8:]}/jobs")
                             for c in parse_search(t)]
                    if not cards:
                        break
                    ctx.stats["pages"] += 1
                    fresh = [c for c in cards if not c["sponsored"] and (c["pub_ms"] is None or c["pub_ms"] / 1000 >= cutoff)]
                    stale = 0 if fresh else stale + 1
                    for c in fresh:
                        if c["id"] in seen:
                            continue
                        seen.add(c["id"])
                        if not is_target_role(c["title"]):
                            ctx.stats["off_target"] += 1
                        elif ctx.known(c["id"], job_url(c["id"])):
                            ctx.stats["skipped_known"] += 1
                        else:
                            queue.append(c)
                    if stale >= 2:
                        break
        queues = [q for q in pending.values() if q]
        while queues:
            for q in list(queues):
                c = q.pop(0)
                for _, t in _captured(session, job_url(c["id"]), f"{BASE[8:]}/viewjob"):
                    d = parse_detail(t)
                    if d:
                        found[c["id"]] = to_listing(c, d)
                        break
                if not q:
                    queues.remove(q)
    except CapReached:
        ctx.stats["capped"] = True
    return list(found.values())
