from job_dashboard.db import init_db, insert_job, upsert_company_classification, query_jobs
from job_dashboard.models import JobListing


def _job(company, url):
    return JobListing(source="test", external_id=None, title="DS", company=company,
                      location="Remote", description="d", job_url=url, job_type=None,
                      is_remote=False, salary_text=None, posted_date=None)


def _seed(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    insert_job(conn, _job("Acme Bank", "http://x/1"))
    insert_job(conn, _job("Globex", "http://x/2"))
    conn.commit()
    upsert_company_classification(conn, "acme bank", "BFSI", "Product", "dict")
    # Globex left unclassified
    return conn


def test_jobs_carry_tags_and_unclassified_is_none(tmp_path):
    conn = _seed(tmp_path)
    jobs, _ = query_jobs(conn, limit=50)
    by_co = {j["company"]: j for j in jobs}
    assert by_co["Acme Bank"]["industry"] == "BFSI"
    assert by_co["Acme Bank"]["company_type"] == "Product"
    assert by_co["Globex"]["industry"] is None  # unclassified, still present


def test_industry_filter_narrows(tmp_path):
    conn = _seed(tmp_path)
    jobs, total = query_jobs(conn, industry="BFSI", limit=50)
    assert total == 1 and jobs[0]["company"] == "Acme Bank"


def test_company_type_filter_narrows(tmp_path):
    conn = _seed(tmp_path)
    jobs, total = query_jobs(conn, company_type="Product", limit=50)
    assert total == 1 and jobs[0]["company"] == "Acme Bank"
