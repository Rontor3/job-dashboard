import pytest

from job_dashboard.db import (
    dashboard_stats, init_db, insert_job, job_detail, mark_duplicate,
    query_jobs, record_llm_evaluation, set_job_status, upsert_embed_score,
)
from job_dashboard.models import JobListing


def _seed(conn, n, **overrides):
    fields = dict(
        source=f"src{n}", title=f"Role {n}", company=f"Co {n}",
        job_url=f"https://x.com/{n}", description=f"desc {n}",
    )
    fields.update(overrides)
    insert_job(conn, JobListing(**fields))
    return conn.execute("SELECT id FROM jobs ORDER BY id DESC").fetchone()[0]


def test_set_job_status_validates_and_updates(tmp_path):
    conn = init_db(tmp_path / "t.db")
    jid = _seed(conn, 1)

    set_job_status(conn, jid, "saved")
    assert conn.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()[0] == "saved"
    set_job_status(conn, jid, None)  # clear back to new
    assert conn.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()[0] is None

    with pytest.raises(ValueError):
        set_job_status(conn, jid, "bogus")
    with pytest.raises(KeyError):
        set_job_status(conn, 99999, "saved")


def test_query_jobs_excludes_dismissed_by_default_but_never_deletes(tmp_path):
    conn = init_db(tmp_path / "t.db")
    a = _seed(conn, 1)
    b = _seed(conn, 2)
    set_job_status(conn, b, "dismissed")

    rows, total = query_jobs(conn)
    assert [r["id"] for r in rows] == [a] and total == 1

    rows, total = query_jobs(conn, include_dismissed=True)
    assert total == 2

    rows, _ = query_jobs(conn, status="dismissed")
    assert [r["id"] for r in rows] == [b]


def test_query_jobs_sorts_by_embed_score_and_min_score_is_opt_in(tmp_path):
    conn = init_db(tmp_path / "t.db")
    lo = _seed(conn, 1)
    hi = _seed(conn, 2)
    unscored = _seed(conn, 3)
    upsert_embed_score(conn, lo, 0.3, "h")
    upsert_embed_score(conn, hi, 0.9, "h")

    rows, total = query_jobs(conn, sort="embed")
    assert total == 3  # unscored still present — scores never gate
    assert [r["id"] for r in rows] == [hi, lo, unscored]

    rows, total = query_jobs(conn, min_score=0.5)
    assert [r["id"] for r in rows] == [hi]


def test_query_jobs_text_search_and_filters(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed(conn, 1, title="ML Engineer", company="Stripe", is_remote=True)
    _seed(conn, 2, title="Chef", company="Bistro", is_remote=False)

    rows, _ = query_jobs(conn, q="stripe")
    assert len(rows) == 1 and rows[0]["company"] == "Stripe"
    rows, _ = query_jobs(conn, remote=True)
    assert len(rows) == 1 and rows[0]["title"] == "ML Engineer"


def test_query_jobs_job_type_filter_is_format_insensitive(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed(conn, 1, job_type="fulltime")
    _seed(conn, 2, job_type="full_time")
    _seed(conn, 3, job_type="FULL_TIME")
    _seed(conn, 4, job_type="contract")

    rows, total = query_jobs(conn, job_type="fulltime")
    assert total == 3
    assert len(rows) == 3


def test_query_jobs_skips_duplicates(tmp_path):
    conn = init_db(tmp_path / "t.db")
    a = _seed(conn, 1)
    b = _seed(conn, 2)
    mark_duplicate(conn, b, a)

    rows, total = query_jobs(conn)
    assert total == 1 and rows[0]["id"] == a


def test_job_detail_includes_scores_lists_and_cross_listings(tmp_path):
    conn = init_db(tmp_path / "t.db")
    a = _seed(conn, 1)
    b = _seed(conn, 2, source="remoteok")
    mark_duplicate(conn, b, a)
    upsert_embed_score(conn, a, 0.8, "h")
    record_llm_evaluation(conn, a, 87, "Strong Fit", ["prod ML"], ["k8s"], {"expired": False})

    detail = job_detail(conn, a)
    assert detail["description"] == "desc 1"
    assert detail["llm_score"] == 87
    assert detail["strengths"] == ["prod ML"]
    assert detail["flags"] == {"expired": False}
    assert detail["cross_listings"][0]["source"] == "remoteok"

    assert job_detail(conn, 99999) is None


def test_job_detail_defaults_empty_lists_when_unranked(tmp_path):
    conn = init_db(tmp_path / "t.db")
    a = _seed(conn, 1)
    detail = job_detail(conn, a)
    assert detail["strengths"] == [] and detail["gaps"] == [] and detail["flags"] == {}


def test_dashboard_stats(tmp_path):
    conn = init_db(tmp_path / "t.db")
    a = _seed(conn, 1)
    b = _seed(conn, 2)
    c = _seed(conn, 3)
    set_job_status(conn, b, "applied")
    upsert_embed_score(conn, a, 0.8, "h")
    record_llm_evaluation(conn, a, 80, "Good Fit", [], [], {})

    stats = dashboard_stats(conn)
    assert stats == {"total": 3, "new": 2, "saved": 0, "applied": 1,
                     "dismissed": 0, "unranked": 2}
