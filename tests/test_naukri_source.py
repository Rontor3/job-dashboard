import json
from dataclasses import dataclass

from job_dashboard.sources import naukri_source
from job_dashboard.models import JobListing


@dataclass
class FakeJob:
    job_id: str = "j1"
    title: str = "ML Engineer"
    company: str = "Acme"
    location: str = "Bengaluru"
    experience: str = "2-5 Yrs"
    salary: str = ""
    posted_date: str = "3 Days Ago"
    apply_link: str = "https://www.naukri.com/job-listings-ml-1"
    description: str = "Build ML pipelines in production."
    tags: tuple = ("python", "ml")


class FakeClient:
    def __init__(self, jobs):
        self._jobs = jobs
    def search_jobs(self, keyword):
        return self._jobs


def _write_session(tmp_path):
    p = tmp_path / "naukri_session.json"
    p.write_text(json.dumps({"token": "t", "cookies": {}, "saved_at": "2026-07-17"}))
    return p


def test_maps_naukri_jobs_to_joblistings(tmp_path):
    sp = _write_session(tmp_path)
    jobs = naukri_source.fetch_naukri_jobs(
        "machine learning engineer", session_path=sp,
        client_factory=lambda sess: FakeClient([FakeJob()]),
    )
    assert len(jobs) == 1
    j = jobs[0]
    assert isinstance(j, JobListing)
    assert j.source == "naukri"
    assert j.title == "ML Engineer"
    assert j.company == "Acme"
    assert j.job_url == "https://www.naukri.com/job-listings-ml-1"
    assert j.description == "Build ML pipelines in production."
    assert j.location == "Bengaluru"
    assert j.is_remote is False


def test_skips_jobs_without_description(tmp_path):
    sp = _write_session(tmp_path)
    jobs = naukri_source.fetch_naukri_jobs(
        "ml", session_path=sp,
        client_factory=lambda sess: FakeClient([FakeJob(description="")]),
    )
    assert jobs == []


def test_returns_empty_when_no_session_file(tmp_path):
    jobs = naukri_source.fetch_naukri_jobs(
        "ml", session_path=tmp_path / "missing.json",
        client_factory=lambda sess: FakeClient([FakeJob()]),
    )
    assert jobs == []


def test_returns_empty_when_client_raises(tmp_path):
    sp = _write_session(tmp_path)
    def boom(_sess):
        raise RuntimeError("naukri blocked / token expired")
    jobs = naukri_source.fetch_naukri_jobs("ml", session_path=sp, client_factory=boom)
    assert jobs == []


def test_returns_empty_when_search_raises(tmp_path):
    sp = _write_session(tmp_path)
    class Angry:
        def search_jobs(self, keyword):
            raise RuntimeError("403")
    jobs = naukri_source.fetch_naukri_jobs("ml", session_path=sp,
                                           client_factory=lambda s: Angry())
    assert jobs == []


def test_returns_empty_when_session_file_is_malformed(tmp_path):
    sp = tmp_path / "naukri_session.json"
    sp.write_text("{not valid json")
    jobs = naukri_source.fetch_naukri_jobs(
        "ml", session_path=sp,
        client_factory=lambda sess: FakeClient([FakeJob()]),
    )
    assert jobs == []


def test_skips_jobs_missing_required_fields(tmp_path):
    sp = _write_session(tmp_path)
    jobs = naukri_source.fetch_naukri_jobs(
        "ml", session_path=sp,
        client_factory=lambda sess: FakeClient([FakeJob(apply_link=None), FakeJob(title="")]),
    )
    assert jobs == []
