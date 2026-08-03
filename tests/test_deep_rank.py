from job_dashboard.db import init_db, insert_job, upsert_embed_score
from job_dashboard.match.deep_rank import deep_rank_unranked, _parse
from job_dashboard.models import JobListing


def _embed_all(conn):
    for (jid,) in conn.execute("SELECT id FROM jobs").fetchall():
        upsert_embed_score(conn, jid, 0.5, "h")
    conn.commit()


def _job(title, company="Acme"):
    return JobListing(source="test", external_id=None, title=title, company=company,
                      location="Remote", description="Build ML models in Python.",
                      job_url=f"http://x/{title}", job_type=None, is_remote=False,
                      salary_text=None, posted_date=None)


def test_parse_extracts_verdict_score_lists():
    r = _parse("Verdict: Good Fit\nScore: 72\nStrengths: Python, ML\nGaps: no Spark")
    assert r["verdict"] == "Good Fit" and r["llm_score"] == 72
    assert "Python" in r["strengths"] and r["gaps"] == ["no Spark"]


def test_parse_defaults_when_unparseable():
    r = _parse("total garbage output")
    assert r["verdict"] == "Moderate Fit" and r["llm_score"] == 50


def test_parse_derives_verdict_from_score_only():
    assert _parse("Score: 84")["verdict"] == "Strong Fit"


def test_batch_nuisance_free_llm_for_rest(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    calls = []
    insert_job(conn, _job("Graphic Designer"))
    insert_job(conn, _job("Machine Learning Engineer"))
    conn.commit()
    _embed_all(conn)
    fake = lambda p: calls.append(p) or "Verdict: Strong Fit\nScore: 88\nStrengths: Python\nGaps: none"
    counts = deep_rank_unranked(conn, llm=fake, profile_text="Python ML 3 years", candidate_years=3)
    assert counts == {"nuisance": 1, "llm": 1, "skipped": 0, "total": 2}
    assert len(calls) == 1  # LLM called only for the non-nuisance job
    rows = dict(conn.execute("SELECT j.title, m.verdict FROM jobs j JOIN match_scores m ON m.job_id = j.id"))
    assert rows["Graphic Designer"] == "Poor Fit"
    assert rows["Machine Learning Engineer"] == "Strong Fit"


def test_batch_is_idempotent(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    insert_job(conn, _job("Data Scientist"))
    conn.commit()
    _embed_all(conn)
    fake = lambda p: "Verdict: Good Fit\nScore: 70"
    deep_rank_unranked(conn, llm=fake, profile_text="x", candidate_years=3)
    second = deep_rank_unranked(conn, llm=fake, profile_text="x", candidate_years=3)
    assert second["total"] == 0  # nothing left to rank
