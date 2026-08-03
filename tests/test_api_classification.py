from fastapi.testclient import TestClient
from job_dashboard.api.app import create_app
from job_dashboard.db import init_db, insert_job, upsert_company_classification
from job_dashboard.models import JobListing


def _job(company, url):
    return JobListing(source="test", external_id=None, title="DS", company=company,
                      location="Remote", description="d", job_url=url, job_type=None,
                      is_remote=False, salary_text=None, posted_date=None)


def _app(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    insert_job(conn, _job("Acme Bank", "http://x/1"))
    insert_job(conn, _job("Globex", "http://x/2"))
    conn.commit()
    upsert_company_classification(conn, "acme bank", "BFSI", "Product", "dict")
    conn.close()
    return TestClient(create_app(db_path=db))


def test_feed_filters_by_industry(tmp_path):
    client = _app(tmp_path)
    r = client.get("/api/jobs?industry=BFSI")
    body = r.json()
    assert body["total"] == 1 and body["jobs"][0]["company"] == "Acme Bank"
    assert body["jobs"][0]["industry"] == "BFSI"


def test_classifications_endpoint(tmp_path):
    client = _app(tmp_path)
    r = client.get("/api/classifications")
    assert r.json() == {"industries": ["BFSI"], "company_types": ["Product"]}
