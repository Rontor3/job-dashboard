"""LinkedIn Jobs adapter. Reads only the responses LinkedIn's own SPA makes when a search page
loads (voyagerJobsDashJobCards + the jobPostingDetailDescription prefetch); no clicks.
Extraction logic verified in docs/career-agent/job-source-research/linkedin_fetch_sketch.py."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from job_dashboard.models import JobListing

from .types import CapReached

SITE = "linkedin"
BASE = "https://www.linkedin.com/jobs/search/"
# 48h verified working (1,093 results vs 900 for 24h, 1,428 for 7d). Max 30 days (retention rule).
TPR = {24: "r86400", 48: "r172800", 168: "r604800", 720: "r2592000"}


def job_url(jid: str) -> str:
    return f"https://www.linkedin.com/jobs/view/{jid}"


def search_url(term, hours=None, start=0, location="India", sort="DD") -> str:
    u = f"{BASE}?keywords={quote(term)}&location={quote(location)}"
    if sort:
        u += f"&sortBy={sort}"
    if hours:
        u += f"&f_TPR={TPR[hours]}"
    if start:
        u += f"&start={start}"
    return u


def _t(x):
    return (x or {}).get("text")


def parse_cards(body):
    inc = body.get("included", [])
    posting = {x["entityUrn"].rsplit(":", 1)[-1]: x for x in inc
               if x.get("$type", "").endswith(".JobPosting") and x.get("entityUrn")}
    out = {}
    for x in inc:
        urn = x.get("jobPostingUrn") or x.get("*jobPosting")
        if not x.get("$type", "").endswith("JobPostingCard") or not x.get("jobPostingTitle") or not urn:
            continue
        jid = urn.rsplit(":", 1)[-1]
        ft = {i["type"]: i for i in x.get("footerItems") or []}
        out[jid] = dict(
            id=jid, title=x["jobPostingTitle"], company=_t(x.get("primaryDescription")),
            location=_t(x.get("secondaryDescription")), salary=_t(x.get("tertiaryDescription")),
            listed_ms=(ft.get("LISTED_DATE") or {}).get("timeAt"),
            easy_apply_card="EASY_APPLY_TEXT" in ft,
            reposted=(posting.get(jid) or {}).get("repostedJob"))
    total = ((body.get("data") or {}).get("paging") or {}).get("total")
    return out, total


def parse_details(body):
    out = {}

    def slot(x):
        return out.setdefault(x["entityUrn"].rsplit(":", 1)[-1], {})
    for x in body.get("included", []):
        t = x.get("$type", "")
        if not x.get("entityUrn"):
            continue
        if t.endswith(".JobDescription"):
            s = slot(x); s["description"] = _t(x.get("descriptionText")); s["posted_on"] = x.get("postedOnText")
        elif t.endswith(".JobSeekerApplicationDetail"):
            slot(x).update(onsite_apply=x.get("onsiteApply"), ats=x.get("applicantTrackingSystemName"),
                           apply_url=x.get("companyApplyUrl"), apply_cta=_t(x.get("applyCtaText")))
        elif t.endswith(".JobPosting") and x.get("createdAt"):
            slot(x)["created_ms"] = x["createdAt"]
    return out


def apply_kind(card, detail) -> str:
    """native = Easy Apply, external = employer/ATS. Card flag matched onsiteApply in 82/82 checked."""
    if detail.get("onsite_apply") is not None:
        return "native" if detail["onsite_apply"] else "external"
    return "native" if card.get("easy_apply_card") else "external"


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat() if ms else None


def to_listing(card, detail) -> JobListing:
    ms = card.get("listed_ms") or detail.get("created_ms")
    posted = _iso(ms)
    return JobListing(
        source=SITE, external_id=card["id"], title=card["title"], company=card.get("company") or "",
        location=card.get("location"), job_url=job_url(card["id"]),
        description=detail.get("description") or "", salary_text=card.get("salary"), posted_date=posted,
        apply_url=detail.get("apply_url"), apply_kind=apply_kind(card, detail))


# Spec terms (docs/career-agent/2026-09-25-cdp-job-fetching-design.md, LinkedIn section).
TERMS = ["machine learning engineer", "ai engineer", "data scientist", "llm engineer",
         "mlops engineer", "senior data scientist", "risk data scientist"]
# 2026-09-27 live check: LinkedIn now carries JobDescription/JobSeekerApplicationDetail inside the
# JobCards responses and in ...JobPostingDetailSections (JOB_DESCRIPTION_CARD); the old
# jobPostingDetailDescription query no longer fires.
_NEEDLES = ("voyagerJobsDashJobCards", "voyagerJobsDashJobPostingDetailSections")


def _load(session, url):
    """One page load -> (cards, details) from the responses LinkedIn's SPA made itself."""
    cards, details = {}, {}
    with session.capture(*_NEEDLES) as cap:
        session.goto(url)
    for u, body in cap.bodies():
        if "voyagerJobsDashJobCards" in u:
            for jid, c in parse_cards(body)[0].items():     # a bare later card must not erase an earlier full one
                old = cards.setdefault(jid, c)
                if old is not c:
                    old.update({k: v for k, v in c.items() if v not in (None, "") and old.get(k) in (None, "")})
        for jid, d in parse_details(body).items():
            details.setdefault(jid, {}).update({k: v for k, v in d.items() if v is not None})
    return cards, details


def run(session, ctx):
    """Phase 1: every search page of every term (cheap, carries prefetched details).
    Phase 2: spend what is left of the load budget on detail loads, round-robin across terms."""
    from job_dashboard.match.relevance import is_target_role
    hours = 720 if ctx.mode == "backfill" else ctx.hours
    ctx.stats.setdefault("off_target", 0)
    found, pending = {}, {}            # pending: term -> [(card, detail)] lacking a description
    seen = set()
    try:
        for term in ctx.terms:
            consecutive_known, queue = 0, pending.setdefault(term, [])
            for p in range(ctx.max_pages):
                cards, details = _load(session, search_url(term, hours, start=50 * p))
                if not cards:
                    break
                ctx.stats["pages"] += 1
                for jid, c in cards.items():
                    if jid in seen:
                        continue
                    seen.add(jid)
                    if not is_target_role(c["title"]):
                        ctx.stats["off_target"] += 1
                        continue
                    if not c.get("company"):
                        continue                        # insert_job would reject it anyway
                    if ctx.known(jid, job_url(jid)):
                        ctx.stats["skipped_known"] += 1
                        consecutive_known += 1
                        # A repost keeps its id but gets a fresh listed time: move the stored date up.
                        if ctx.redate and c.get("listed_ms") and ctx.redate(jid, job_url(jid), _iso(c["listed_ms"])):
                            ctx.stats["redated"] = ctx.stats.get("redated", 0) + 1
                        continue
                    d = details.get(jid) or {}
                    if d.get("description"):
                        found[jid] = to_listing(c, d)
                    else:
                        queue.append((c, d))
                    consecutive_known = 0
                if ctx.mode == "incremental" and consecutive_known >= ctx.stop_after_known:
                    break
        queues = [q for q in pending.values() if q]
        while queues:
            for q in list(queues):
                c, _ = q.pop(0)
                d = _load(session, job_url(c["id"]))[1].get(c["id"]) or {}
                if d.get("description"):                # else retried next run; deliberately not "known"
                    found[c["id"]] = to_listing(c, d)
                if not q:
                    queues.remove(q)
    except CapReached:
        ctx.stats["capped"] = True
    return list(found.values())
