from unittest.mock import patch

from job_dashboard import source_registry as sr
from job_dashboard.models import JobListing


def _job(title):
    return JobListing(source="jobspy:indeed", title=title, company="c", job_url=f"https://x/{title}", description="d")


def test_loose_terms_are_gone():
    for t in ("ml platform engineer", "research engineer", "forward deployed engineer", "ai solutions engineer"):
        assert t not in sr.SEARCH_TERMS


def test_jobspy_is_retired_and_himalayas_results_are_title_gated():
    assert sr.REGION_SEARCHES == []
    jobs = [_job("AI Engineer"), _job("Social Media Executive")]
    with patch.object(sr, "fetch_jobspy_jobs", side_effect=AssertionError("jobspy must not run")), \
            patch.object(sr, "fetch_himalayas_jobs", return_value=jobs):
        himalayas = sr.job_sources()[1]           # per term: remotive, himalayas, naukri
        assert [j.title for j in himalayas()] == ["AI Engineer"]
