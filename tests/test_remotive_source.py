from job_dashboard.sources import remotive_source
from tests.conftest import FakeResponse


def test_fetch_remotive_jobs_maps_response(monkeypatch):
    payload = {
        "jobs": [
            {
                "id": 987, "title": "AI Engineer", "company_name": "Remote Co",
                "candidate_required_location": "Worldwide",
                "description": "<p>Build AI systems</p>",
                "url": "https://remotive.com/job/987",
                "job_type": "full_time", "salary": "$120,000 - $150,000",
                "publication_date": "2026-07-05T00:00:00",
            }
        ]
    }
    monkeypatch.setattr(
        remotive_source.requests, "get", lambda *a, **k: FakeResponse(json_data=payload)
    )

    jobs = remotive_source.fetch_remotive_jobs("AI engineer")

    assert len(jobs) == 1
    assert jobs[0].source == "remotive"
    assert jobs[0].title == "AI Engineer"
    assert jobs[0].job_url == "https://remotive.com/job/987"
    assert jobs[0].is_remote is True


def test_fetch_remotive_jobs_skips_rows_without_description(monkeypatch):
    payload = {
        "jobs": [
            {
                "id": 1, "title": "No JD", "company_name": "Empty Co",
                "candidate_required_location": "Worldwide", "description": "",
                "url": "https://remotive.com/job/1",
            },
            {
                "id": 2, "title": "Has JD", "company_name": "Real Co",
                "candidate_required_location": "Worldwide",
                "description": "<p>Actual job description</p>",
                "url": "https://remotive.com/job/2",
            },
        ]
    }
    monkeypatch.setattr(
        remotive_source.requests, "get", lambda *a, **k: FakeResponse(json_data=payload)
    )

    jobs = remotive_source.fetch_remotive_jobs("AI engineer")

    assert len(jobs) == 1
    assert jobs[0].job_url == "https://remotive.com/job/2"
