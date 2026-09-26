"""LinkedIn Jobs adapter. Reads only the responses LinkedIn's own SPA makes when a search page
loads (voyagerJobsDashJobCards + the jobPostingDetailDescription prefetch); no clicks.
Extraction logic verified in docs/career-agent/job-source-research/linkedin_fetch_sketch.py."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from job_dashboard.models import JobListing

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


def to_listing(card, detail) -> JobListing:
    ms = card.get("listed_ms") or detail.get("created_ms")
    posted = datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat() if ms else None
    return JobListing(
        source=SITE, external_id=card["id"], title=card["title"], company=card.get("company") or "",
        location=card.get("location"), job_url=job_url(card["id"]),
        description=detail.get("description") or "", salary_text=card.get("salary"), posted_date=posted,
        apply_url=detail.get("apply_url"), apply_kind=apply_kind(card, detail))
