import pytest

from job_dashboard.db import (
    get_resume, init_db, insert_job, resumes_for_job, save_resume,
)
from job_dashboard.models import JobListing


def _seed(conn, n, **overrides):
    """Helper to insert a test job and return its id."""
    fields = dict(
        source=f"src{n}", title=f"Role {n}", company=f"Co {n}",
        job_url=f"https://x.com/{n}", description=f"desc {n}",
    )
    fields.update(overrides)
    insert_job(conn, JobListing(**fields))
    return conn.execute("SELECT id FROM jobs ORDER BY id DESC").fetchone()[0]


def test_save_resume_returns_id_and_stores_data(tmp_path):
    """save_resume stores blocks_used and ats_report as JSON, returns new id."""
    conn = init_db(tmp_path / "t.db")
    job_id = _seed(conn, 1)

    resume_id = save_resume(
        conn, job_id, "path/to/resume.pdf",
        blocks_used=["contact", "experience"],
        ats_score=0.85,
        ats_report={"match": "good", "warnings": []},
    )

    assert isinstance(resume_id, int)
    assert resume_id > 0


def test_resumes_for_job_round_trips_json_and_returns_newest_first(tmp_path):
    """resumes_for_job parses JSON for blocks_used and ats_report, orders by created_at DESC."""
    conn = init_db(tmp_path / "t.db")
    job_id = _seed(conn, 1)

    # Insert two resumes
    rid1 = save_resume(
        conn, job_id, "v1.pdf",
        blocks_used=["contact"],
        ats_score=0.7,
        ats_report={"status": "v1"},
    )
    rid2 = save_resume(
        conn, job_id, "v2.pdf",
        blocks_used=["contact", "experience"],
        ats_score=0.9,
        ats_report={"status": "v2"},
    )

    resumes = resumes_for_job(conn, job_id)

    assert len(resumes) == 2
    # Newest first (rid2 inserted second)
    assert resumes[0]["id"] == rid2
    assert resumes[1]["id"] == rid1

    # Check JSON round-trip
    assert resumes[0]["blocks_used"] == ["contact", "experience"]
    assert resumes[0]["ats_report"] == {"status": "v2"}
    assert resumes[1]["blocks_used"] == ["contact"]
    assert resumes[1]["ats_report"] == {"status": "v1"}

    # Check other fields
    assert resumes[0]["job_id"] == job_id
    assert resumes[0]["pdf_path"] == "v2.pdf"
    assert resumes[0]["ats_score"] == 0.9


def test_resumes_for_job_empty_for_unknown_job(tmp_path):
    """resumes_for_job returns empty list for job with no resumes."""
    conn = init_db(tmp_path / "t.db")
    job_id = _seed(conn, 1)

    resumes = resumes_for_job(conn, job_id)

    assert resumes == []


def test_get_resume_returns_dict_with_parsed_json(tmp_path):
    """get_resume returns resume dict, parsing JSON fields."""
    conn = init_db(tmp_path / "t.db")
    job_id = _seed(conn, 1)

    resume_id = save_resume(
        conn, job_id, "resume.pdf",
        blocks_used=["contact", "skills"],
        ats_score=0.75,
        ats_report={"quality": "good"},
    )

    resume = get_resume(conn, resume_id)

    assert resume is not None
    assert resume["id"] == resume_id
    assert resume["job_id"] == job_id
    assert resume["pdf_path"] == "resume.pdf"
    assert resume["blocks_used"] == ["contact", "skills"]
    assert resume["ats_score"] == 0.75
    assert resume["ats_report"] == {"quality": "good"}
    assert "created_at" in resume


def test_get_resume_returns_none_for_unknown_id(tmp_path):
    """get_resume returns None if resume doesn't exist."""
    conn = init_db(tmp_path / "t.db")

    resume = get_resume(conn, 99999)

    assert resume is None


def test_resume_created_at_is_set_automatically(tmp_path):
    """save_resume sets created_at to current time."""
    conn = init_db(tmp_path / "t.db")
    job_id = _seed(conn, 1)

    resume_id = save_resume(
        conn, job_id, "r.pdf",
        blocks_used=[],
        ats_score=0.5,
        ats_report={},
    )

    resume = get_resume(conn, resume_id)
    assert resume["created_at"] is not None
    # ISO format check
    assert "T" in resume["created_at"]
