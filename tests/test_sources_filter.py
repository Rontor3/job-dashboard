from job_dashboard.db import init_db, insert_job, distinct_sources
from job_dashboard.models import JobListing


def _job(source, url):
    return JobListing(source=source, external_id=None, title="DS", company="Acme",
                      location="Remote", description="d", job_url=url, job_type=None,
                      is_remote=False, salary_text=None, posted_date=None)


def test_distinct_sources_includes_naukri_wellfound_sorted(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    insert_job(conn, _job("naukri", "http://x/1"))
    insert_job(conn, _job("wellfound", "http://x/2"))
    insert_job(conn, _job("jobspy:linkedin", "http://x/3"))
    insert_job(conn, _job("naukri", "http://x/4"))  # dupe source collapses
    conn.commit()
    assert distinct_sources(conn) == ["jobspy:linkedin", "naukri", "wellfound"]


def test_distinct_sources_empty_db(tmp_path):
    conn = init_db(str(tmp_path / "e.db"))
    assert distinct_sources(conn) == []
