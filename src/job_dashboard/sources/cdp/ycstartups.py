"""Y Combinator's Work at a Startup (workatastartup.com) adapter. Not Wellfound — a separate site.
Reads only the documents the site's own pages load: `/jobs/search?q=` returns the search JSON directly
(captured passively, like Naukri/LinkedIn); a job's `/jobs/<id>` page is plain public HTML, no login.
No pagination exists on this site (`page=`/`offset=` are ignored, always the same top-30 relevance
results per query) and the search JSON carries no posted-date field, so every job's `posted_date` is
None (kept, not dropped — the site-wide rule for undated jobs). `applyUrl` in the search JSON is a
stale per-visit signup link and is never stored; apply is always the platform's own YC-account flow.
"""
from __future__ import annotations

import html as _html
import json
import re
from urllib.parse import quote_plus

from job_dashboard.models import JobListing
from job_dashboard.sources.cdp.types import CapReached, html_to_text

SITE = "ycstartups"
BASE = "https://www.workatastartup.com"
NEEDLE = "workatastartup.com/jobs/search"
TERMS = ["machine learning engineer", "ai engineer", "data scientist", "llm engineer", "mlops engineer"]
# The job page is a Next.js app-router page: the description lives as `descriptionHtml` inside a
# React island's serialized props, doubly escaped (JSON string escapes, then HTML-attribute escapes
# on top since the blob sits inside an HTML attribute) — not a plain <div> in the DOM/raw HTML.
_DESCRIPTION = re.compile(r'&quot;descriptionHtml&quot;:&quot;(.*?)&quot;,&quot;', re.S)


def search_url(term: str) -> str:
    return f"{BASE}/jobs/search?q={quote_plus(term + ' india')}"


def job_url(job_id) -> str:
    return f"{BASE}/jobs/{job_id}"


def parse_search(body) -> list:
    return [dict(id=j["id"], title=j["title"], company=j["companyName"], location=j.get("location"),
                 job_type=j.get("jobType"), salary=j.get("salary"))
            for j in body.get("jobs", []) if isinstance(j, dict) and j.get("id") and j.get("title") and j.get("companyName")]


def parse_detail(html: str):
    m = _DESCRIPTION.search(html or "")
    if not m:
        return None
    try:
        # Undo the HTML-attribute escaping (&quot;/&#39;/&amp;), then decode the JSON string escapes
        # (<, \n, \") that were applied when the page embedded this as JSON.
        decoded = json.loads('"' + _html.unescape(m.group(1)) + '"')
    except ValueError:
        return None
    text = html_to_text(decoded)
    return text or None


def to_listing(card, description) -> JobListing:
    return JobListing(
        source=SITE, external_id=str(card["id"]), title=card["title"], company=card["company"],
        location=card.get("location"), job_url=job_url(card["id"]), description=description,
        job_type=card.get("job_type"), salary_text=card.get("salary"), posted_date=None,
        apply_url=None, apply_kind="native")


def _search(session, url):
    with session.capture(NEEDLE) as cap:
        session.goto(url)
    for _, body in cap.bodies():
        return parse_search(body)
    return []


def _detail(session, url):
    with session.capture(url) as cap:
        session.goto(url)
    for _, _, text in cap.texts():
        return parse_detail(text)
    return None


def run(session, ctx):
    from job_dashboard.match.relevance import is_target_role
    seen, queue, found = set(), [], {}
    ctx.partial = found                  # salvaged by the runner if this run dies midway
    ctx.stats.setdefault("off_target", 0)
    try:
        for term in ctx.terms:
            for c in _search(session, search_url(term)):
                if c["id"] in seen:
                    continue
                seen.add(c["id"])
                if not is_target_role(c["title"]):
                    ctx.stats["off_target"] += 1
                elif ctx.known(str(c["id"]), job_url(c["id"])):
                    ctx.stats["skipped_known"] += 1
                else:
                    queue.append(c)
            ctx.stats["pages"] += 1
        for c in queue:
            desc = _detail(session, job_url(c["id"]))
            if desc:
                found[c["id"]] = to_listing(c, desc)
    except CapReached:
        ctx.stats["capped"] = True
    return list(found.values())
