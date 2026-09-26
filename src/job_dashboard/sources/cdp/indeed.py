"""Indeed adapter (India + Remote). Reads only the documents Indeed's own pages load: the search page embeds
the job cards as window.mosaic JSON, a job page embeds a JSON-LD JobPosting. No API replay, no clicks.
Any Cloudflare/Turnstile challenge is a hard stop (Blocked), never solved or retried."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import quote_plus

from job_dashboard.models import JobListing
from job_dashboard.sources.cdp.types import html_to_text

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
