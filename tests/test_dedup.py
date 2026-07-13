from job_dashboard.db import init_db, insert_job, suspected_duplicates
from job_dashboard.match.dedup import mark_duplicates, normalized_key
from job_dashboard.models import JobListing


def _job(source, title, company, url):
    return JobListing(source=source, title=title, company=company,
                      job_url=url, description="full jd text")


def test_normalized_key_strips_punctuation_and_case():
    assert normalized_key("Acme, Inc.", "Sr. ML Engineer") == \
        normalized_key("acme inc", "sr ml engineer")
    assert normalized_key("Acme", "ML Engineer") != normalized_key("Acme", "Data Engineer")


def test_same_role_across_sources_marks_later_as_duplicate(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job("jobspy:linkedin", "ML Engineer", "Acme", "https://li.com/1"))
    insert_job(conn, _job("remoteok", "ML Engineer", "Acme", "https://rok.com/2"))
    insert_job(conn, _job("remotive", "Data Scientist", "Beta", "https://rmt.com/3"))

    marked = mark_duplicates(conn)

    assert marked == 1
    dupes = suspected_duplicates(conn)
    assert len(dupes) == 1
    assert dupes[0]["source"] == "remoteok"
    assert dupes[0]["canonical_source"] == "jobspy:linkedin"


def test_near_miss_titles_are_not_merged(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job("a", "Senior ML Engineer", "Acme", "https://x.com/1"))
    insert_job(conn, _job("b", "ML Engineer", "Acme", "https://x.com/2"))

    assert mark_duplicates(conn) == 0


def test_mark_duplicates_is_idempotent(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job("a", "ML Engineer", "Acme", "https://x.com/1"))
    insert_job(conn, _job("b", "ML Engineer", "Acme", "https://x.com/2"))

    assert mark_duplicates(conn) == 1
    assert mark_duplicates(conn) == 0  # second run marks nothing new
