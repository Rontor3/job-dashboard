from unittest.mock import patch

from job_dashboard import source_registry as sr
from job_dashboard.models import JobListing


def _job(title):
    return JobListing(source="jobspy:indeed", title=title, company="c", job_url=f"https://x/{title}", description="d")


def test_loose_terms_are_gone():
    for t in ("ml platform engineer", "research engineer", "forward deployed engineer", "ai solutions engineer"):
        assert t not in sr.SEARCH_TERMS


def test_jobspy_results_are_title_gated():
    with patch.object(sr, "fetch_jobspy_jobs", return_value=[_job("AI Engineer"), _job("Social Media Executive")]):
        first = sr.job_sources()[0]
        assert [j.title for j in first()] == ["AI Engineer"]
