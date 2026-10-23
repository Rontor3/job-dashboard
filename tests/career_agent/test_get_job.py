import sqlite3
from job_dashboard.db import get_job


def test_get_job_returns_title_company_description_location():
    """The location feeds the bank's per-job rules (sponsorship by country, relocation by city)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT, company TEXT, description TEXT, location TEXT)")
    conn.execute("INSERT INTO jobs (id, title, company, description, location) "
                 "VALUES (1, 'Data Scientist', 'Acme', 'Build ML.', 'KA, IN')")
    conn.commit()
    assert get_job(conn, 1) == {"title": "Data Scientist", "company": "Acme", "description": "Build ML.",
                                "location": "KA, IN"}
    assert get_job(conn, 999) is None
