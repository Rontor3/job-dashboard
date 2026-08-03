from job_dashboard.db import init_db, insert_job, get_company_classification
from job_dashboard.classify.run import classify_unclassified
from job_dashboard.models import JobListing


def _job(company, url, title="DS", desc="d"):
    return JobListing(source="test", external_id=None, title=title, company=company,
                      location="Remote", description=desc, job_url=url, job_type=None,
                      is_remote=False, salary_text=None, posted_date=None)


def test_classifies_all_and_is_idempotent(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    insert_job(conn, _job("Accenture", "http://x/1"))     # dict hit
    insert_job(conn, _job("Zzz Labs", "http://x/2"))       # llm fallback
    conn.commit()
    fake = lambda p: "Industry: AI/ML & Data Platforms\nCompany-type: Startup"
    r1 = classify_unclassified(conn, llm=fake)
    assert r1["dict"] == 1 and r1["llm"] == 1
    assert get_company_classification(conn, "accenture")["industry"] == "Consulting & IT Services"
    assert get_company_classification(conn, "zzz labs")["company_type"] == "Startup"
    # second run: nothing left to classify
    r2 = classify_unclassified(conn, llm=fake)
    assert r2["dict"] == 0 and r2["llm"] == 0 and r2["total"] == 0
