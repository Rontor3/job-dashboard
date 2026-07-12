from job_dashboard.sources import remoteok_source
from tests.conftest import FakeResponse


def test_fetch_remoteok_jobs_skips_legal_notice_and_maps_jobs(monkeypatch):
    payload = [
        {"legal": "API Terms of Service..."},
        {
            "id": "555", "position": "Senior Data Scientist", "company": "DataCo",
            "location": "", "description": "Analyze data at scale",
            "apply_url": "https://remoteok.com/remote-jobs/555",
            "tags": ["python", "contract"],
            "salary_min": 100000, "salary_max": 140000,
            "date": "2026-07-08T00:00:00",
        },
    ]
    monkeypatch.setattr(
        remoteok_source.requests, "get", lambda *a, **k: FakeResponse(json_data=payload)
    )

    jobs = remoteok_source.fetch_remoteok_jobs()

    assert len(jobs) == 1
    assert jobs[0].title == "Senior Data Scientist"
    assert jobs[0].job_type == "contract"
    assert jobs[0].salary_text == "$100000-$140000"


def test_fetch_remoteok_jobs_skips_rows_without_description(monkeypatch):
    payload = [
        {"legal": "API Terms of Service..."},
        {
            "id": "1", "position": "No JD Role", "company": "Empty Co",
            "location": "", "description": "",
            "apply_url": "https://remoteok.com/remote-jobs/1",
        },
        {
            "id": "2", "position": "Real Role", "company": "Real Co",
            "location": "", "description": "Actual job description",
            "apply_url": "https://remoteok.com/remote-jobs/2",
        },
    ]
    monkeypatch.setattr(
        remoteok_source.requests, "get", lambda *a, **k: FakeResponse(json_data=payload)
    )

    jobs = remoteok_source.fetch_remoteok_jobs()

    assert len(jobs) == 1
    assert jobs[0].job_url == "https://remoteok.com/remote-jobs/2"
