from job_dashboard.db import (
    init_db, insert_job, upsert_embed_score, record_llm_evaluation, query_jobs,
)
from job_dashboard.models import JobListing


def _seed(conn, url, embed, llm=None):
    insert_job(conn, JobListing(source="t", external_id=None, title="ML Engineer",
                                company="Co", location="R", description="d", job_url=url,
                                job_type=None, is_remote=False, salary_text=None,
                                posted_date="2026-08-01"))
    jid = conn.execute("SELECT id FROM jobs WHERE job_url = ?", (url,)).fetchone()[0]
    upsert_embed_score(conn, jid, embed, "h")
    if llm is not None:
        record_llm_evaluation(conn, jid, llm, "Good Fit", [], [], {})
    conn.commit()
    return jid


def test_min_score_filters_the_displayed_fit_number(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    # The feed card shows llm_score when present, else embed*100. The Min slider
    # must filter that exact number, whatever the sort.
    lo = _seed(conn, "u/lo", 0.9, 30)     # high embed but shows LLM 30 → hidden at min 50
    hi = _seed(conn, "u/hi", 0.2, 80)     # low embed but shows LLM 80 → shown at min 50
    nollm = _seed(conn, "u/nollm", 0.7)   # no LLM → shows embed 70 → shown at min 50

    for sort in ("embed", "llm", "date"):
        ids = {j["id"] for j in query_jobs(conn, sort=sort, min_score=0.5, limit=50)[0]}
        assert ids == {hi, nollm}, f"sort={sort}"

    # min 0 (slider off) shows everything
    assert len(query_jobs(conn, min_score=None, limit=50)[0]) == 3
