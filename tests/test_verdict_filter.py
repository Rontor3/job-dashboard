from job_dashboard.db import (
    init_db, insert_job, upsert_embed_score, record_llm_evaluation, query_jobs,
)
from job_dashboard.models import JobListing


def _job(title, url):
    return JobListing(source="test", external_id=None, title=title, company="Acme",
                      location="Remote", description="d", job_url=url, job_type=None,
                      is_remote=False, salary_text=None, posted_date=None)


def test_verdict_filter_narrows_to_that_fit(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    insert_job(conn, _job("A", "http://x/1"))
    insert_job(conn, _job("B", "http://x/2"))
    conn.commit()
    ids = [r[0] for r in conn.execute("SELECT id FROM jobs ORDER BY id")]
    for i in ids:
        upsert_embed_score(conn, i, 0.5, "h")
    record_llm_evaluation(conn, ids[0], llm_score=88, verdict="Strong Fit", strengths=[], gaps=[], flags={})
    record_llm_evaluation(conn, ids[1], llm_score=40, verdict="Weak Fit", strengths=[], gaps=[], flags={})
    conn.commit()

    jobs, total = query_jobs(conn, verdict="Strong Fit")
    assert total == 1 and jobs[0]["verdict"] == "Strong Fit"
    # no verdict filter -> both returned
    assert query_jobs(conn)[1] == 2
