import sqlite3
from job_dashboard.db import (
    init_db, insert_job, upsert_company_classification,
    get_company_classification, unclassified_companies,
    distinct_classification_values,
)
from job_dashboard.models import JobListing


def _job(company, title="Data Scientist"):
    return JobListing(source="test", external_id=None, title=title, company=company,
                      location="Remote", description="d", job_url=f"http://x/{company}/{title}",
                      job_type=None, is_remote=False, salary_text=None, posted_date=None)


def test_upsert_and_get_roundtrip(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    upsert_company_classification(conn, "acme", "BFSI", "Product", "dict")
    row = get_company_classification(conn, "acme")
    assert row["industry"] == "BFSI" and row["company_type"] == "Product" and row["method"] == "dict"


def test_upsert_updates_single_row(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    upsert_company_classification(conn, "acme", "BFSI", "Product", "dict")
    upsert_company_classification(conn, "acme", "Fintech", "Startup", "llm")
    row = get_company_classification(conn, "acme")
    assert row["industry"] == "Fintech" and row["method"] == "llm"
    assert conn.execute("SELECT COUNT(*) FROM company_classifications").fetchone()[0] == 1


def test_unclassified_companies_excludes_classified_and_dupes(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    insert_job(conn, _job("Acme", "DS"))
    insert_job(conn, _job("Acme", "MLE"))   # same company, different job
    insert_job(conn, _job("Globex", "DS"))
    conn.commit()
    upsert_company_classification(conn, "acme", "BFSI", "Product", "dict")
    got = unclassified_companies(conn)
    assert got == ["globex"]  # acme classified; acme dupe collapsed by key


def test_distinct_values_sorted_uniques(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    upsert_company_classification(conn, "a", "BFSI", "Product", "dict")
    upsert_company_classification(conn, "b", "BFSI", "Startup", "llm")
    vals = distinct_classification_values(conn)
    assert vals["industries"] == ["BFSI"]
    assert vals["company_types"] == ["Product", "Startup"]
