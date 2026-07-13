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

SEARCH_TERMS = ["machine learning engineer", "ai engineer", "senior data scientist"]


def job_sources():
    fetchers = []
    for term in SEARCH_TERMS:
        fetchers.append(lambda t=term: fetch_jobspy_jobs(t, "Remote", ["linkedin", "indeed"]))
        fetchers.append(lambda t=term: fetch_remotive_jobs(t))
        fetchers.append(lambda t=term: fetch_himalayas_jobs(t))
    fetchers.append(lambda: fetch_remoteok_jobs())
    fetchers.append(lambda: fetch_wwr_jobs())
    return fetchers


def company_sources():
    return [lambda: fetch_funded_startups()]
