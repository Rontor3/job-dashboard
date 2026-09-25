import pytest

from job_dashboard import qa_store
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing


@pytest.fixture
def conn(tmp_path):
    c = init_db(str(tmp_path / "t.db"))
    for n in (1, 2):
        insert_job(c, JobListing(source="s", title=f"T{n}", company=f"C{n}",
                                 job_url=f"https://x/{n}", description="jd"))
    yield c
    c.close()


def _q(conn, job, run, ref, label, **kw):
    qa_store.record(conn, job_id=job, run_key=run, ref=ref, label=label, **kw)


def test_record_upserts_and_keeps_earlier_fields(conn):
    _q(conn, 1, "r1", "#a", "Why us?", status="needs_answer", confidence=40,
       basis="guessed", context_json={"prompt": "p"})
    _q(conn, 1, "r1", "#a", "Why us?", answer="drafted")
    (row,) = qa_store.open_questions(conn, 1)
    assert row["answer"] == "drafted" and row["confidence"] == 40
    assert row["context_json"] == {"prompt": "p"}
    assert conn.execute("select count(*) from application_qa").fetchone()[0] == 1


def test_record_rejects_unknown_field(conn):
    with pytest.raises(ValueError):
        _q(conn, 1, "r1", "#a", "Q", bogus=1)


def test_open_only_when_newest_row_still_open(conn):
    _q(conn, 1, "r1", "#a", "Notice period?", status="needs_answer")
    assert len(qa_store.open_questions(conn, 1)) == 1
    _q(conn, 1, "r2", "#a", "Notice period?", status="filled", source="recall")  # later run fills it
    assert qa_store.open_questions(conn, 1) == []


def test_mark_answered_closes_and_counts_by_job(conn):
    _q(conn, 1, "r1", "#a", "Why us?", status="needs_answer")
    _q(conn, 2, "r9", "#a", "Why us?", status="needs_answer")
    assert qa_store.open_counts(conn) == {1: 1, 2: 1}
    assert qa_store.mark_answered(conn, 1, qa_store.norm_key("Why us?"), "because") == 1
    assert qa_store.open_counts(conn) == {2: 1}
    assert qa_store.open_questions(conn, 1) == []


def test_asked_in_counts_distinct_jobs_and_applications(conn):
    _q(conn, 1, "r1", "#a", "Notice period?", status="filled")
    _q(conn, 1, "r2", "#a", "Notice period?", status="filled")   # same job re-run
    _q(conn, 2, "r9", "#a", "Notice period?", status="filled")
    key = qa_store.norm_key("Notice period?")
    assert qa_store.asked_in_counts(conn)[key] == 2
    assert {a["job_id"] for a in qa_store.applications_for(conn, key)} == {1, 2}


def test_settings_default_set_and_clamp(conn):
    assert qa_store.confidence_min(conn) == 60
    qa_store.set_setting(conn, "answer_confidence_min", 75)
    assert qa_store.confidence_min(conn) == 75
    qa_store.set_setting(conn, "answer_confidence_min", 900)
    assert qa_store.confidence_min(conn) == 100
    with pytest.raises(KeyError):
        qa_store.set_setting(conn, "nope", 1)


def _seed(conn):
    kw = dict(kind="text", status="filled")
    _q(conn, 1, "a", "#1", "Notice period?", source="learned", retrieval_kind="label_exact",
       retrieved_qkey="notice period", retrieval_score=1.0, outcome="kept", **kw)
    _q(conn, 1, "a", "#2", "Years of Python?", source="learned", retrieval_kind="fts_fuzzy",
       retrieved_qkey="years of java", retrieval_score=0.6, outcome="edited", **kw)
    _q(conn, 2, "b", "#2", "Years of Rust?", source="learned", retrieval_kind="fts_fuzzy",
       retrieved_qkey="years of java", retrieval_score=0.5, outcome="edited", **kw)
    _q(conn, 2, "b", "#3", "Why us?", source="judgment", confidence=80, outcome="kept", **kw)
    _q(conn, 2, "b", "#4", "Describe a project", source="judgment", confidence=40, outcome="edited", **kw)
    _q(conn, 2, "b", "#5", "Favourite colour", status="needs_answer", kind="text", retrieval_kind="none")
    _q(conn, 2, "b", "#6", "Tell me more", source="human", retrieval_kind="semantic",     # hit, but not used
       retrieved_qkey="tell us more", retrieval_score=0.3, **kw)


def test_retrieval_stats(conn):
    _seed(conn)
    s = qa_store.retrieval_stats(conn)
    assert s["total_fields"] == 7 and s["retrieval_hits"] == 4
    assert s["by_tier"] == {"label_exact": 1, "fts_fuzzy": 2, "semantic": 1}
    assert s["answered_by_memory"] == 3 and s["retrieved_not_used"] == 1
    assert s["reviewed"] == {"kept": 1, "edited": 2, "wrong_rate": 0.667}
    assert s["top_wrong_entries"] == [{"qkey": "years of java", "edited": 2, "kept": 0}]
    assert s["by_source"]["unanswered"] == 1
    g = s["generation"]
    assert (g["kept"]["avg_confidence"], g["edited"]["avg_confidence"]) == (80.0, 40.0)


def test_retrieval_stats_empty_db(conn):
    s = qa_store.retrieval_stats(conn)
    assert s["total_fields"] == 0 and s["hit_rate"] is None and s["reviewed"]["wrong_rate"] is None


def test_answers_used_newest_per_question_and_set_outcome(conn):
    _q(conn, 1, "r1", "#1", "Notice period?", status="filled", answer="old")
    _q(conn, 1, "r2", "#1", "Notice period?", status="filled", answer="new")
    _q(conn, 1, "r2", "#2", "Why?", status="needs_answer")
    (row,) = qa_store.answers_used(conn, 1)
    assert row["answer"] == "new"
    assert qa_store.set_outcome(conn, row["id"], "edited")
    assert qa_store.answers_used(conn, 1)[0]["outcome"] == "edited"
    with pytest.raises(ValueError):
        qa_store.set_outcome(conn, row["id"], "maybe")


def test_recent_retrievals_newest_first_with_job(conn):
    _seed(conn)
    r = qa_store.recent_retrievals(conn, 3)
    assert len(r) == 3 and r[0]["label"] == "Tell me more" and r[0]["title"] == "T2"
