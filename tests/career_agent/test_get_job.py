import sqlite3
from job_dashboard.db import get_job


def test_get_job_returns_job_facts_and_apply_details():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT, company TEXT, location TEXT, description TEXT, apply_details TEXT)")
    conn.execute("INSERT INTO jobs (id, title, company, location, description) VALUES (1, 'Data Scientist', 'Acme', 'Noida', 'Build ML.')")
    conn.execute("""INSERT INTO jobs VALUES (2, 'MLE', 'Beta', NULL, 'x', '{"referrer": "Jane"}')""")
    conn.commit()
    assert get_job(conn, 1) == {"title": "Data Scientist", "company": "Acme", "location": "Noida",
                                "description": "Build ML.", "apply_details": {}}
    assert get_job(conn, 2)["apply_details"] == {"referrer": "Jane"}
    assert get_job(conn, 999) is None


def test_local_or_escape_resolves_for_a_job_loaded_by_get_job(tmp_path, fake_embed):
    """The apply run hands get_job's dict to the bank; the local-city rule needs its location."""
    from career_agent.memory import qbank
    from career_agent.memory.qbank_match import resolve_value
    from job_dashboard.db import init_db, insert_job
    from job_dashboard.models import JobListing
    conn = init_db(str(tmp_path / "j.db"))
    qbank.seed_if_empty(conn, fake_embed)
    qbank.set_answer(conn, "home_address", "C-12, Sector 5, Noida 201301")
    qbank.set_answer(conn, "local_cities", "Noida, Delhi")
    for i, loc in enumerate(["Noida, Uttar Pradesh, India", "London, UK"]):
        insert_job(conn, JobListing(source="linkedin", title="MLE", company="Acme", location=loc,
                                    job_url=f"https://x/{i}", description="d", external_id=str(i)))
    entry = qbank.get_entry(conn, "work_location")
    ids = [r[0] for r in conn.execute("SELECT id FROM jobs ORDER BY id")]
    answers = [resolve_value(conn, entry, question=entry["question"], escape="relocating",
                             job=get_job(conn, jid), contact={}) for jid in ids]
    assert answers == ["C-12, Sector 5, Noida 201301", "relocating"]
