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
