from job_dashboard.sources import himalayas_source
from tests.conftest import FakeResponse


def test_fetch_himalayas_jobs_maps_response(monkeypatch):
    payload = {
        "jobs": [
            {
                "guid": "abc-123", "title": "Senior ML Engineer",
                "companyName": "Himalayas Co", "employmentType": "Full Time",
                "locationRestrictions": ["United States", "India"],
                "description": "<p>Own the ML platform</p>",
                "applicationLink": "https://himalayas.app/jobs/abc-123",
                "minSalary": 130000, "maxSalary": 170000, "currency": "USD",
                "pubDate": "2026-07-06T00:00:00Z",
            }
        ]
    }
    monkeypatch.setattr(
        himalayas_source.requests, "get", lambda *a, **k: FakeResponse(json_data=payload)
    )

    jobs = himalayas_source.fetch_himalayas_jobs("machine learning")

    assert len(jobs) == 1
    assert jobs[0].title == "Senior ML Engineer"
    assert jobs[0].location == "United States, India"
    assert jobs[0].salary_text == "130000-170000 USD"


def test_fetch_himalayas_jobs_skips_rows_without_description(monkeypatch):
    payload = {
        "jobs": [
            {
                "guid": "no-jd", "title": "No JD Role", "companyName": "Empty Co",
                "locationRestrictions": ["United States"], "description": "",
                "applicationLink": "https://himalayas.app/jobs/no-jd",
            },
            {
                "guid": "has-jd", "title": "Real Role", "companyName": "Real Co",
                "locationRestrictions": ["India"],
                "description": "<p>Own the ML platform</p>",
                "applicationLink": "https://himalayas.app/jobs/has-jd",
            },
        ]
    }
    monkeypatch.setattr(
        himalayas_source.requests, "get", lambda *a, **k: FakeResponse(json_data=payload)
    )

    jobs = himalayas_source.fetch_himalayas_jobs("machine learning")

    assert len(jobs) == 1
    assert jobs[0].job_url == "https://himalayas.app/jobs/has-jd"
