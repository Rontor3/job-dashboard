import pandas as pd

from job_dashboard.sources import jobspy_source


def _fake_multirow_df():
    """Realistic multi-row DataFrame.

    Row (a): full row - salary + id + description present.
    Row (b): missing salary/id/posted_date. Because these columns also
        contain numeric values in row (a), pandas upcasts them to float64
        and row (b)'s missing values become NaN (not None).
    Row (c): missing/empty description - must be skipped entirely.
    """
    return pd.DataFrame(
        [
            {
                "id": 1001,
                "site": "indeed",
                "title": "Machine Learning Engineer",
                "company": "Acme AI",
                "location": "Remote",
                "description": "Full JD text here",
                "job_url": "https://indeed.com/job/123",
                "job_type": "fulltime",
                "is_remote": True,
                "min_amount": 120000,
                "max_amount": 160000,
                "currency": "USD",
                "date_posted": "2026-07-01",
            },
            {
                "id": None,
                "site": "linkedin",
                "title": "AI Engineer",
                "company": "Beta",
                "location": "Bangalore",
                "description": "JD text for row b",
                "job_url": "https://linkedin.com/job/1",
                "job_type": "fulltime",
                "is_remote": False,
                "min_amount": None,
                "max_amount": None,
                "currency": None,
                "date_posted": None,
            },
            {
                "id": 1003,
                "site": "glassdoor",
                "title": "Data Scientist",
                "company": "Gamma",
                "location": "New York",
                "description": "",
                "job_url": "https://glassdoor.com/job/9",
                "job_type": "fulltime",
                "is_remote": False,
                "min_amount": 90000,
                "max_amount": 110000,
                "currency": "USD",
                "date_posted": "2026-07-03",
            },
        ]
    )


def test_fetch_jobspy_jobs_maps_multirow_dataframe_and_skips_description_less_row(monkeypatch):
    fake_df = _fake_multirow_df()
    monkeypatch.setattr(jobspy_source, "scrape_jobs", lambda **kwargs: fake_df)

    jobs = jobspy_source.fetch_jobspy_jobs("machine learning engineer", "Remote", ["indeed"])

    # Row (c) has no description text and must be skipped -> only 2 listings.
    assert len(jobs) == 2

    job_a, job_b = jobs

    assert job_a.source == "jobspy:indeed"
    assert job_a.title == "Machine Learning Engineer"
    assert job_a.company == "Acme AI"
    assert job_a.job_url == "https://indeed.com/job/123"
    assert job_a.is_remote is True
    assert job_a.salary_text == "120000-160000 USD"

    assert job_b.source == "jobspy:linkedin"
    assert job_b.title == "AI Engineer"
    assert job_b.description == "JD text for row b"
    assert job_b.is_remote is False
    assert job_b.salary_text is None
    assert job_b.external_id is None
    assert job_b.posted_date is None


def test_fetch_jobspy_jobs_skips_rows_without_description(monkeypatch):
    fake_df = _fake_multirow_df()
    monkeypatch.setattr(jobspy_source, "scrape_jobs", lambda **kwargs: fake_df)

    jobs = jobspy_source.fetch_jobspy_jobs("data scientist", "New York", ["glassdoor"])

    titles = [job.title for job in jobs]
    assert "Data Scientist" not in titles


def test_fetch_jobspy_jobs_no_nan_leakage_into_fields(monkeypatch):
    fake_df = _fake_multirow_df()
    monkeypatch.setattr(jobspy_source, "scrape_jobs", lambda **kwargs: fake_df)

    jobs = jobspy_source.fetch_jobspy_jobs("ai", "any", ["indeed", "linkedin", "glassdoor"])

    for job in jobs:
        assert job.external_id != "nan"
        assert job.posted_date != "nan"
        assert job.salary_text != "nan-nan"


def test_fetch_jobspy_jobs_fetches_linkedin_descriptions_and_passes_country(monkeypatch):
    captured = {}

    def fake_scrape(**kwargs):
        captured.update(kwargs)
        return pd.DataFrame([])

    monkeypatch.setattr(jobspy_source, "scrape_jobs", fake_scrape)

    jobspy_source.fetch_jobspy_jobs("ml engineer", "India", ["linkedin", "indeed"], country="India")

    assert captured["linkedin_fetch_description"] is True
    assert captured["country_indeed"] == "India"


def test_fetch_jobspy_jobs_omits_country_when_not_given(monkeypatch):
    captured = {}

    def fake_scrape(**kwargs):
        captured.update(kwargs)
        return pd.DataFrame([])

    monkeypatch.setattr(jobspy_source, "scrape_jobs", fake_scrape)

    jobspy_source.fetch_jobspy_jobs("ml engineer", "Remote", ["indeed"])

    assert "country_indeed" not in captured
