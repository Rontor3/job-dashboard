from job_dashboard.db import insert_job, upsert_company


def run_ingest(conn, job_sources, company_sources):
    """job_sources/company_sources: lists of no-arg callables returning
    list[JobListing] / list[Company] respectively.

    Each source is isolated: if one raises (a flaky board, a parse error),
    it's counted in ``source_errors`` and the remaining sources still run,
    rather than aborting the whole batch.
    """
    new_jobs = 0
    source_errors = 0
    for fetch in job_sources:
        try:
            listings = fetch()
        except Exception:
            source_errors += 1
            continue
        for job in listings:
            if insert_job(conn, job):
                new_jobs += 1

    companies_seen = 0
    for fetch in company_sources:
        try:
            companies = fetch()
        except Exception:
            source_errors += 1
            continue
        for company in companies:
            upsert_company(conn, company)
            companies_seen += 1

    return {
        "new_jobs": new_jobs,
        "companies_seen": companies_seen,
        "source_errors": source_errors,
    }
