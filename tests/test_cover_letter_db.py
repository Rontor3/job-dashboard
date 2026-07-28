import pytest

from job_dashboard.db import (
    get_cover_letter, init_db, insert_job, cover_letters_for_job, save_cover_letter,
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


def test_save_cover_letter_returns_id_and_stores_data(tmp_path):
    """save_cover_letter stores body and company_facts_used as JSON, returns new id."""
    conn = init_db(tmp_path / "t.db")
    job_id = _seed(conn, 1)

    cl_id = save_cover_letter(
        conn, job_id, "path/to/cover.pdf",
        body="Dear hiring manager...",
        company_facts_used=["raised Series A", "remote-first"],
    )

    assert isinstance(cl_id, int)
    assert cl_id > 0


def test_cover_letters_for_job_round_trips_json_and_returns_newest_first(tmp_path):
    """cover_letters_for_job parses JSON for company_facts_used, orders by created_at DESC."""
    conn = init_db(tmp_path / "t.db")
    job_id = _seed(conn, 1)

    clid1 = save_cover_letter(
        conn, job_id, "v1.pdf",
        body="body v1",
        company_facts_used=["fact1"],
    )
    clid2 = save_cover_letter(
        conn, job_id, "v2.pdf",
        body="body v2",
        company_facts_used=["fact1", "fact2"],
    )

    cover_letters = cover_letters_for_job(conn, job_id)

    assert len(cover_letters) == 2
    # Newest first (clid2 inserted second)
    assert cover_letters[0]["id"] == clid2
    assert cover_letters[1]["id"] == clid1

    # Check JSON round-trip
    assert cover_letters[0]["company_facts_used"] == ["fact1", "fact2"]
    assert cover_letters[1]["company_facts_used"] == ["fact1"]

    # Check other fields
    assert cover_letters[0]["job_id"] == job_id
    assert cover_letters[0]["pdf_path"] == "v2.pdf"
    assert cover_letters[0]["body"] == "body v2"


def test_cover_letters_for_job_empty_for_unknown_job(tmp_path):
    """cover_letters_for_job returns empty list for job with no cover letters."""
    conn = init_db(tmp_path / "t.db")
    job_id = _seed(conn, 1)

    cover_letters = cover_letters_for_job(conn, job_id)

    assert cover_letters == []


def test_get_cover_letter_returns_dict_with_parsed_json(tmp_path):
    """get_cover_letter returns cover letter dict, parsing JSON fields."""
    conn = init_db(tmp_path / "t.db")
    job_id = _seed(conn, 1)

    cl_id = save_cover_letter(
        conn, job_id, "cover.pdf",
        body="Dear hiring manager, I am excited...",
        company_facts_used=["raised Series A", "10 employees"],
    )

    cover_letter = get_cover_letter(conn, cl_id)

    assert cover_letter is not None
    assert cover_letter["id"] == cl_id
    assert cover_letter["job_id"] == job_id
    assert cover_letter["pdf_path"] == "cover.pdf"
    assert cover_letter["body"] == "Dear hiring manager, I am excited..."
    assert cover_letter["company_facts_used"] == ["raised Series A", "10 employees"]
    assert "created_at" in cover_letter


def test_get_cover_letter_returns_none_for_unknown_id(tmp_path):
    """get_cover_letter returns None if cover letter doesn't exist."""
    conn = init_db(tmp_path / "t.db")

    cover_letter = get_cover_letter(conn, 99999)

    assert cover_letter is None


def test_cover_letter_created_at_is_set_automatically(tmp_path):
    """save_cover_letter sets created_at to current time."""
    conn = init_db(tmp_path / "t.db")
    job_id = _seed(conn, 1)

    cl_id = save_cover_letter(
        conn, job_id, "r.pdf",
        body="",
        company_facts_used=[],
    )

    cover_letter = get_cover_letter(conn, cl_id)
    assert cover_letter["created_at"] is not None
    # ISO format check
    assert "T" in cover_letter["created_at"]


def test_init_db_twice_is_idempotent(tmp_path):
    """Calling init_db twice on the same path does not error."""
    path = tmp_path / "t.db"
    init_db(path)
    conn = init_db(path)
    assert conn is not None
