from job_dashboard import ingest
from job_dashboard.db import init_db
from job_dashboard.models import Company, JobListing


def test_run_ingest_dedupes_jobs_and_upserts_companies(tmp_path):
    conn = init_db(tmp_path / "test.db")
    job = JobListing(
        source="test", title="ML Engineer", company="Acme",
        job_url="https://example.com/1", description="desc",
    )
    company = Company(name="Acme", funding_amount="$1M")

    result = ingest.run_ingest(
        conn,
        job_sources=[lambda: [job], lambda: [job]],  # duplicate source on purpose
        company_sources=[lambda: [company]],
    )

    assert result == {"new_jobs": 1, "companies_seen": 1, "source_errors": 0}
    row_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert row_count == 1


def test_run_ingest_isolates_a_failing_source(tmp_path):
    conn = init_db(tmp_path / "test.db")
    good = JobListing(
        source="test", title="ML Engineer", company="Acme",
        job_url="https://example.com/1", description="desc",
    )

    def boom():
        raise RuntimeError("network down")

    # A raising source must not abort the run — remaining sources still ingest.
    result = ingest.run_ingest(
        conn,
        job_sources=[boom, lambda: [good]],
        company_sources=[],
    )

    assert result == {"new_jobs": 1, "companies_seen": 0, "source_errors": 1}
    row_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert row_count == 1
