"""Daily expiry sweep: soft-hide jobs that are closed, stale, or an obvious
bad fit — so the feed stays live and relevant.

Reasons a job gets hidden (``expired`` flag, reversible):
  - ``bad-fit``  — Poor Fit verdict or a nuisance title (designer, professor…).
  - ``stale``    — older than ``max_age_days`` (uses the freshness normalizer).
  - ``closed``   — the posting URL reports it's no longer open.

Liveness of the URL is checked cheaply over HTTP for most sources; LinkedIn and
Naukri bot-wall plain HTTP, so those go through an injected ``browser_check``
(a real browser) — and, to save time, only for jobs worth it (``llm_score`` above
``llm_gate``). Zero LLM tokens: everything here is HTTP + string matching.
"""
from __future__ import annotations

from job_dashboard.db import mark_job_expired, sweep_candidates
from job_dashboard.match.compensation import job_ctc_lpa
from job_dashboard.match.freshness import job_age_days
from job_dashboard.match.relevance import is_target_role, nuisance_match

# Keyword-blind / loose-search sources whose off-target titles should be pruned.
_DUMP_SOURCES = ("remoteok", "remotive")

# Text that means "this posting is no longer open", lower-cased substring match.
CLOSED_MARKERS = (
    "no longer accepting applications",
    "no longer active",
    "this job is no longer available",
    "job posting has expired",
    "position has been filled",
    "this position is no longer",
    "applications are closed",
    "posting is expired",
)
# Hosts that bot-wall scripted HTTP — check these with the browser instead.
_BROWSER_HOSTS = ("linkedin.com", "naukri.com")


def is_bad_fit(job) -> bool:
    return (job.get("verdict") == "Poor Fit") or bool(nuisance_match(job.get("title")))


def _needs_browser(url) -> bool:
    return any(h in (url or "") for h in _BROWSER_HOSTS)


def http_liveness(url, fetch=None):
    """True=open, False=closed, None=unknown/skip. ``fetch(url) -> (status, text)``."""
    if not url:
        return None
    fetch = fetch or _default_fetch
    try:
        status, text = fetch(url)
    except Exception:  # noqa: BLE001 — network hiccup → unknown, don't hide
        return None
    if status in (404, 410):
        return False
    if status != 200:
        return None  # 3xx/5xx/etc — inconclusive
    low = (text or "").lower()
    return not any(m in low for m in CLOSED_MARKERS)


def _default_fetch(url):
    import ssl
    import urllib.request
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")})
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def sweep(conn, *, http_fetch=None, browser_check=None, llm_gate=50,
          max_age_days=45, min_ctc_lpa=25, now=None, on_progress=None):
    """Run the expiry sweep. Marks jobs expired; returns counts by reason.

    ``browser_check(url) -> bool|None`` checks a bot-walled URL with a real
    browser (open/closed/unknown); if omitted, LinkedIn/Naukri jobs are pruned
    by age/bad-fit only, never wrongly closed. ``min_ctc_lpa`` hides roles whose
    STATED annual CTC is below the floor (jobs with no stated CTC are kept).
    """
    counts = {"bad-fit": 0, "off-target": 0, "stale": 0, "low-ctc": 0,
              "closed": 0, "checked": 0}
    for job in sweep_candidates(conn):
        try:
            if on_progress:
                on_progress(job)

            if is_bad_fit(job):
                mark_job_expired(conn, job["id"], "bad-fit")
                counts["bad-fit"] += 1
                continue

            # Board-dump sources (remoteok/remotive) — drop non-ML/AI/DS titles.
            if job.get("source") in _DUMP_SOURCES and not is_target_role(job.get("title")):
                mark_job_expired(conn, job["id"], "off-target")
                counts["off-target"] += 1
                continue

            if min_ctc_lpa is not None:
                ctc = job_ctc_lpa(job.get("salary_text"), job.get("description"))
                if ctc is not None and ctc < min_ctc_lpa:
                    mark_job_expired(conn, job["id"], "low-ctc")
                    counts["low-ctc"] += 1
                    continue

            age = job_age_days(job.get("posted_date"), job.get("fetched_at"), now=now)
            if age is not None and age > max_age_days:
                mark_job_expired(conn, job["id"], "stale")
                counts["stale"] += 1
                continue

            counts["checked"] += 1
            url = job.get("job_url")
            if _needs_browser(url):
                # Expensive path — only for worthwhile fits, and only if a
                # browser checker was supplied.
                if browser_check is None or (job.get("llm_score") or 0) <= llm_gate:
                    continue
                alive = browser_check(url)
            else:
                alive = http_liveness(url, fetch=http_fetch)

            if alive is False:
                mark_job_expired(conn, job["id"], "closed")
                counts["closed"] += 1
        except Exception:  # noqa: BLE001 — one bad job never aborts the sweep
            continue
    return counts
