import pandas as pd

from job_dashboard.sources import jobspy_source


def test_fetch_jobspy_jobs_maps_dataframe_rows_to_joblistings(monkeypatch):
    fake_df = pd.DataFrame([
        {
            "id": "in-123", "site": "indeed", "title": "Machine Learning Engineer",
            "company": "Acme AI", "location": "Remote",
            "description": "Full JD text here", "job_url": "https://indeed.com/job/123",
            "job_type": "fulltime", "is_remote": True,
            "min_amount": 120000, "max_amount": 160000, "currency": "USD",
            "date_posted": "2026-07-01",
        }
    ])
    monkeypatch.setattr(jobspy_source, "scrape_jobs", lambda **kwargs: fake_df)

    jobs = jobspy_source.fetch_jobspy_jobs("machine learning engineer", "Remote", ["indeed"])

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "jobspy:indeed"
    assert job.title == "Machine Learning Engineer"
    assert job.company == "Acme AI"
    assert job.job_url == "https://indeed.com/job/123"
    assert job.is_remote is True
    assert job.salary_text == "120000-160000 USD"


def test_fetch_jobspy_jobs_handles_missing_salary(monkeypatch):
    fake_df = pd.DataFrame([
        {
            "id": "li-1", "site": "linkedin", "title": "AI Engineer", "company": "Beta",
            "location": "Bangalore", "description": "JD text",
            "job_url": "https://linkedin.com/job/1", "job_type": "fulltime",
            "is_remote": False, "min_amount": None, "max_amount": None,
            "currency": None, "date_posted": "2026-07-02",
        }
    ])
    monkeypatch.setattr(jobspy_source, "scrape_jobs", lambda **kwargs: fake_df)

    jobs = jobspy_source.fetch_jobspy_jobs("ai engineer", "Bangalore", ["linkedin"])

    assert jobs[0].salary_text is None
