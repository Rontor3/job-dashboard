from job_dashboard.models import JobListing, Company


def test_job_listing_requires_core_fields_and_defaults_optional_ones():
    job = JobListing(
        source="test",
        title="ML Engineer",
        company="Acme",
        job_url="https://example.com/1",
        description="Full JD text",
    )
    assert job.source == "test"
    assert job.location is None
    assert job.job_type is None
    assert job.is_remote is None


def test_company_defaults_source_to_startup_sheet():
    company = Company(name="Acme")
    assert company.name == "Acme"
    assert company.source == "startup_sheet"
    assert company.funding_amount is None
