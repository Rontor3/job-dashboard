"""Registry wiring the real fetchers into run_pipeline.

Adding a source later = one entry here. Query terms are kept broad across the
profile's target titles (see search-queries.md) — remote-first, not overfit.
"""
from job_dashboard.sources.himalayas_source import fetch_himalayas_jobs
from job_dashboard.sources.jobspy_source import fetch_jobspy_jobs
from job_dashboard.sources.naukri_source import fetch_naukri_jobs
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
    "ml platform engineer",
    # Research (fellowship/residency angle)
    "research engineer",
    # Domain-tilted (fraud/risk — candidate's Tata AIG edge)
    "fraud data scientist",
    "risk data scientist",
    # Emerging titles (2026 market — user flagged 2026-08-04)
    "forward deployed engineer",
    "applied ai engineer",
    "ai solutions engineer",
    "machine learning scientist",
    "genai engineer",
]

# Geographic strategy (user constraint 2026-07-17, no US work visa):
#   US      -> remote-only searches
#   Europe  -> remote-preferred searches
#   India   -> remote + hybrid + onsite all welcome (indeed regionalized via
#              country param; naukri direct dropped from jobspy 2026-07-17 —
#              captcha-blocked 406. Replaced by fetch_naukri_jobs below, the
#              vendored-NopeRi read-only source fed by a cached login session
#              — see scripts/naukri_login.py)
REGION_SEARCHES = [
    ("Remote", ["linkedin", "indeed"], None),        # US/global remote
    ("European Union", ["linkedin"], None),          # Europe
    ("India", ["linkedin", "indeed"], "India"),      # India, all work modes
    # Google Jobs aggregates Naukri/Shine/Foundit/company pages for India —
    # the legitimate route to Naukri inventory while its API captcha-blocks.
    ("India", ["google"], None),
]


def job_sources():
    fetchers = []
    for term in SEARCH_TERMS:
        for location, sites, country in REGION_SEARCHES:
            fetchers.append(
                lambda t=term, loc=location, s=sites, c=country: fetch_jobspy_jobs(
                    t, loc, s, country=c
                )
            )
        fetchers.append(lambda t=term: fetch_remotive_jobs(t))
        fetchers.append(lambda t=term: fetch_himalayas_jobs(t))
        fetchers.append(lambda t=term: fetch_naukri_jobs(t))
    fetchers.append(lambda: fetch_remoteok_jobs())
    fetchers.append(lambda: fetch_wwr_jobs())
    return fetchers


# Wellfound is an ON-DEMAND BROWSER source, deliberately NOT in job_sources():
# it has no public API and gates its GraphQL feed behind login + bot protection,
# so it can't run in the unattended refresh. Instead the candidate's logged-in
# browser feed is read and passed to sources.wellfound_source.wellfound_jobs_from_raw
# (see docs/wellfound-ingest-runbook.md), which yields the same JobListing shape.


def company_sources():
    return [lambda: fetch_funded_startups()]
