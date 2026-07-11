from job_dashboard.db import init_db, job_exists, insert_job, upsert_company
from job_dashboard.models import JobListing, Company


def test_insert_job_then_job_exists(tmp_path):
    conn = init_db(tmp_path / "test.db")
    job = JobListing(
        source="test", title="ML Engineer", company="Acme",
        job_url="https://example.com/1", description="desc",
    )

    assert job_exists(conn, job.job_url) is False
    inserted = insert_job(conn, job)
    assert inserted is True
    assert job_exists(conn, job.job_url) is True


def test_insert_job_is_idempotent_on_job_url(tmp_path):
    conn = init_db(tmp_path / "test.db")
    job = JobListing(
        source="test", title="ML Engineer", company="Acme",
        job_url="https://example.com/1", description="desc",
    )
    insert_job(conn, job)
    second_insert = insert_job(conn, job)

    assert second_insert is False
    count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert count == 1


def test_upsert_company_inserts_then_updates_without_clobbering_contact(tmp_path):
    conn = init_db(tmp_path / "test.db")
    upsert_company(conn, Company(name="Acme", funding_amount="$1M"))
    conn.execute(
        "UPDATE companies SET contact_email = ? WHERE name = ?",
        ("ceo@acme.com", "Acme"),
    )
    conn.commit()

    upsert_company(conn, Company(name="Acme", funding_amount="$2M"))

    row = conn.execute(
        "SELECT funding_amount, contact_email FROM companies WHERE name = ?",
        ("Acme",),
    ).fetchone()
    assert row[0] == "$2M"
    assert row[1] == "ceo@acme.com"
    count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    assert count == 1
