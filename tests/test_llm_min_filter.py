from job_dashboard.db import (
    init_db, insert_job, upsert_embed_score, record_llm_evaluation, query_jobs,
)
from job_dashboard.models import JobListing


def _seed(conn, url, embed, llm):
    insert_job(conn, JobListing(source="t", external_id=None, title="ML Engineer",
                                company="Co", location="R", description="d", job_url=url,
                                job_type=None, is_remote=False, salary_text=None,
                                posted_date="2026-08-01"))
    jid = conn.execute("SELECT id FROM jobs WHERE job_url = ?", (url,)).fetchone()[0]
    upsert_embed_score(conn, jid, embed, "h")
    record_llm_evaluation(conn, jid, llm, "Good Fit", [], [], {})
    conn.commit()
    return jid


def test_min_score_filters_by_active_sort_metric(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    lo = _seed(conn, "u/lo", 0.9, 30)   # high embed, low LLM
    hi = _seed(conn, "u/hi", 0.2, 80)   # low embed, high LLM

    # Sorting by LLM: the 0-1 slider (0.5) means "LLM >= 50" → only the hi-LLM job.
    llm_ids = {j["id"] for j in query_jobs(conn, sort="llm", min_score=0.5, limit=50)[0]}
    assert llm_ids == {hi}

    # Sorting by embed keeps the old behaviour: embed >= 0.5 → only the hi-embed job.
    embed_ids = {j["id"] for j in query_jobs(conn, sort="embed", min_score=0.5, limit=50)[0]}
    assert embed_ids == {lo}
