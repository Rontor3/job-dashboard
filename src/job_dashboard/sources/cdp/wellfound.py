"""Wellfound adapter. The /jobs page fires the signed JobSearchResultsX operation once; we learn its header
template and operation id from that exchange (memory only) and replay the same operation, with our own
variables, from inside the tab. Fails closed on any error. Never opens job detail pages."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from job_dashboard.models import JobListing
from job_dashboard.sources.cdp.types import Blocked, CapReached, html_to_text

SITE = "wellfound"
HOSTS = ("wellfound.com",)
INDIA = "1647"
KEEP = {"x-apollo-signature", "x-wf-cfp", "x-angellist-dd-client-referrer-resource",
        "x-requested-with", "apollographql-client-name", "content-type"}
# Wellfound shows <= 3 jobs per startup, so relevant jobs hide behind the cap: also query by title.
TITLES = ["Data Scientist", "Machine Learning Engineer", "AI Engineer", "NLP Engineer",
          "LLM Engineer", "MLOps Engineer", "Applied Scientist", "Data Scientist L1"]
TITLE_PAGES = 3


def parse_results(body):
    res = ((body.get("data") or {}).get("talent") or {}).get("jobSearchResults") or {}
    jobs = []
    for e in (res.get("startups") or {}).get("edges") or []:
        n = e.get("node") or {}
        for x in n.get("highlightedJobListings") or []:
            if x.get("id") and x.get("title") and n.get("name"):
                jobs.append({"id": str(x["id"]), "slug": x.get("slug") or "", "title": x["title"],
                             "company": n["name"], "description": x.get("description") or "",
                             "live": x.get("liveStartAt"), "auto": bool(x.get("autoPosted")),
                             "location": ", ".join(x.get("locationNames") or []) or None})
    return jobs, bool(res.get("hasNextPage"))


def job_url(j) -> str:
    return f"https://wellfound.com/jobs/{j['id']}-{j['slug']}"


def to_listing(j) -> JobListing:
    return JobListing(
        source=SITE, external_id=j["id"], title=j["title"], company=j["company"], location=j["location"],
        job_url=job_url(j), description=html_to_text(j["description"]),
        posted_date=datetime.fromtimestamp(j["live"], timezone.utc).isoformat() if j.get("live") else None,
        apply_kind="external" if j["auto"] else "native")


def _template(session):
    with session.capture("graphql") as cap:
        session.goto("https://wellfound.com/jobs")
    for headers, body, _ in cap.exchanges():
        if isinstance(body, dict) and body.get("operationName") == "JobSearchResultsX":
            return {"headers": {k: v for k, v in headers.items() if k.lower() in KEEP},
                    "op": (body.get("extensions") or {}).get("operationId")}
    raise Blocked("feed request not seen (logged out or challenged)")


def _query(session, tpl, page, title=None):
    f = {"page": page, "equity": {"min": None, "max": None}, "remotePreference": "NO_REMOTE",
         "salary": {"min": None, "max": None}, "yearsExperience": {"min": None, "max": None},
         "sortBy": "LAST_POSTED", "hideOffPlatformJobs": False, "locationTagIds": [INDIA]}
    if title:
        f["customJobTitles"] = [title]
    body = json.dumps({"operationName": "JobSearchResultsX", "variables": {"filterConfigurationInput": f},
                       "extensions": {"operationId": tpl["op"]}})
    headers = dict(tpl["headers"], **{"x-apollo-operation-name": "JobSearchResultsX"})
    data = json.loads(session.fetch("https://wellfound.com/graphql", hosts=HOSTS, method="POST",
                                    headers=headers, body=body))
    if data.get("errors"):
        raise Blocked(f"graphql error: {data['errors'][0].get('message', '?')}")
    return parse_results(data)


def _iso(sec):
    return datetime.fromtimestamp(sec, timezone.utc).isoformat()


def run(session, ctx):
    cutoff = time.time() - (720 if ctx.mode == "backfill" else ctx.hours) * 3600
    seen, found = set(), []

    def walk(tpl, title, max_pages):
        stale = 0
        for pg in range(1, max_pages + 1):
            jobs, has_next = _query(session, tpl, pg, title)
            ctx.stats["pages"] += 1
            fresh = [j for j in jobs if (j["live"] or 0) >= cutoff]
            for j in fresh:
                if j["id"] in seen:
                    continue
                seen.add(j["id"])
                if ctx.known(j["id"], job_url(j)):
                    ctx.stats["skipped_known"] += 1
                    if ctx.redate and ctx.redate(j["id"], job_url(j), _iso(j["live"])):
                        ctx.stats["redated"] = ctx.stats.get("redated", 0) + 1
                else:
                    found.append(to_listing(j))
            stale = 0 if fresh else stale + 1
            if stale >= 2 or not has_next:
                break

    try:
        tpl = _template(session)
        walk(tpl, None, ctx.max_pages)
        for t in TITLES:
            walk(tpl, t, TITLE_PAGES)
    except CapReached:
        ctx.stats["capped"] = True
    return found
