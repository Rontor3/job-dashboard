"""Registry wiring the real fetchers into run_pipeline.

Adding a source later = one entry here. Query terms are kept broad across the
profile's target titles (see search-queries.md) — remote-first, not overfit.
"""
from job_dashboard.sources.himalayas_source import fetch_himalayas_jobs
from job_dashboard.sources.jobspy_source import fetch_jobspy_jobs
from job_dashboard.sources.remoteok_source import fetch_remoteok_jobs
from job_dashboard.sources.remotive_source import fetch_remotive_jobs
from job_dashboard.sources.startup_sheet import fetch_funded_startups
from job_dashboard.sources.wwr_source import fetch_wwr_jobs

SEARCH_TERMS = [
    # Core ML/AI engineering
    "machine learning engineer",
    "ai engineer",
    "ai/ml engineer",
    "applied machine learning engineer",
    "applied scientist",
    "deep learning engineer",
    # GenAI / LLM tilt (candidate's strongest current direction)
    "llm engineer",
    "generative ai engineer",
    "nlp engineer",
    # Data science ladder (incl. new-title variants)
    "data scientist",
    "senior data scientist",
    "data scientist iii",
    "staff data scientist",
    "lead data scientist",
    # Platform / ops
    "mlops engineer",
    # Domain-tilted (fraud/risk — candidate's Tata AIG edge)
    "fraud data scientist",
    "risk data scientist",
    # Emerging titles
    "applied ai engineer",
    "machine learning scientist",
    "genai engineer",
]

# Geographic strategy (user constraint 2026-07-17, no US work visa):
#   US      -> remote-only searches
#   Europe  -> remote-preferred searches
#   India   -> remote + hybrid + onsite all welcome (indeed regionalized via
#              country param). LinkedIn and Naukri are browser (CDP) sources
#              now (sources/cdp/); the old jobspy-LinkedIn and fetch_naukri_jobs
#              wiring was removed 2026-10-03 (naukri_source.py kept, unwired).
# LinkedIn is a browser (CDP) source. Indeed's web page sits behind a
# Cloudflare challenge in CDP, but jobspy hits Indeed's API and isn't blocked.
REGION_SEARCHES = [("India", ["indeed"], "india")]


def _target_only(jobs):
    """Keep only ML/AI/DS-titled jobs from a keyword-blind/loose source."""
    from job_dashboard.match.relevance import is_target_role
    return [j for j in (jobs or []) if is_target_role(getattr(j, "title", ""))]


def job_sources():
    fetchers = []
    for term in SEARCH_TERMS:
        for location, sites, country in REGION_SEARCHES:
            fetchers.append(
                lambda t=term, loc=location, s=sites, c=country: _target_only(
                    fetch_jobspy_jobs(t, loc, s, country=c, max_age_days=30)
                )
            )
        fetchers.append(lambda t=term: _target_only(fetch_remotive_jobs(t)))
        fetchers.append(lambda t=term: _target_only(fetch_himalayas_jobs(t)))
    # remoteok has no keyword search — it returns its entire board — and
    # remotive's search is loose, so both are gated to ML/AI/DS titles only.
    fetchers.append(lambda: _target_only(fetch_remoteok_jobs()))
    fetchers.append(lambda: fetch_wwr_jobs())
    return fetchers


# Wellfound is an ON-DEMAND BROWSER source, deliberately NOT in job_sources():
# it has no public API and gates its GraphQL feed behind login + bot protection,
# so it can't run in the unattended refresh. Instead the candidate's logged-in
# browser feed is read and passed to sources.wellfound_source.wellfound_jobs_from_raw
# (see docs/wellfound-ingest-runbook.md), which yields the same JobListing shape.


def company_sources():
    return [lambda: fetch_funded_startups()]
