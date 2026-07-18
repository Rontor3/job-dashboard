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
    "ml platform engineer",
    # Research (fellowship/residency angle)
    "research engineer",
    # Domain-tilted (fraud/risk — candidate's Tata AIG edge)
    "fraud data scientist",
    "risk data scientist",
]

# Geographic strategy (user constraint 2026-07-17, no US work visa):
#   US      -> remote-only searches
#   Europe  -> remote-preferred searches
#   India   -> remote + hybrid + onsite all welcome (indeed regionalized via
#              country param; naukri dropped 2026-07-17 — captcha-blocked 406,
#              revisit in the Scrapling follow-up plan)
REGION_SEARCHES = [
    ("Remote", ["linkedin", "indeed"], None),        # US/global remote
    ("European Union", ["linkedin"], None),          # Europe
    ("India", ["linkedin", "indeed"], "India"),      # India, all work modes
    # Google Jobs aggregates Naukri/Shine/Foundit/company pages for India —
    # the legitimate route to Naukri inventory while its API captcha-blocks.
    ("India", ["google"], None),
    # Naukri direct: captcha-blocked (406) as of 2026-07-17 but intermittent;
    # per-source isolation makes it a free bet — contributes when unblocked.
    ("India", ["naukri"], None),
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
    fetchers.append(lambda: fetch_remoteok_jobs())
    fetchers.append(lambda: fetch_wwr_jobs())
    return fetchers


def company_sources():
    return [lambda: fetch_funded_startups()]
