from job_dashboard.sources.wellfound_source import wellfound_jobs_from_raw
from job_dashboard.models import JobListing


def test_normalizes_a_row_with_years_and_region_in_description():
    raw = [{
        "slug": "4521063-lead-data-scientist", "title": "Lead Data Scientist / AI/ML Engineer",
        "company": "talentxo", "location": "Pune", "remote": True,
        "salary": "₹50L – ₹55L", "skills": ["Python", "Fraud"],
        "years_experience": 10, "hires_remotely_in": "India",
        "description": "Build production ML for fraud detection.",
    }]
    jobs = wellfound_jobs_from_raw(raw)
    assert len(jobs) == 1
    j = jobs[0]
    assert isinstance(j, JobListing) and j.source == "wellfound"
    assert j.job_url == "https://wellfound.com/jobs/4521063-lead-data-scientist"
    assert j.company == "talentxo"
    assert "10 years of exp" in j.description and "Hires remotely in: India" in j.description


def test_skips_rows_without_slug_or_description():
    raw = [
        {"title": "X", "company": "Y", "description": "d"},          # no slug
        {"slug": "s", "company": "Y", "description": "d"},           # no title
        {"slug": "s2", "title": "T", "company": "Y"},               # no description
    ]
    assert wellfound_jobs_from_raw(raw) == []


def test_bad_row_does_not_raise():
    assert wellfound_jobs_from_raw([None, 42, {"slug": "s", "title": "T",
                                               "company": "C", "description": "hi"}])
