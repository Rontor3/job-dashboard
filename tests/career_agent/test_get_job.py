import sqlite3
from job_dashboard.db import get_job


def test_get_job_returns_title_company_description():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT, company TEXT, description TEXT)")
    conn.execute("INSERT INTO jobs (id, title, company, description) VALUES (1, 'Data Scientist', 'Acme', 'Build ML.')")
    conn.commit()
    assert get_job(conn, 1) == {"title": "Data Scientist", "company": "Acme", "description": "Build ML."}
    assert get_job(conn, 999) is None
