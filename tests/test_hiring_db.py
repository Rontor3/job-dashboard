from datetime import datetime, timezone, timedelta
from job_dashboard.db import (
    init_db, upsert_hiring_post, hiring_posts, dismiss_hiring_post,
)


def _post(url, fit, fetched_at, **kw):
    base = dict(url=url, poster_name="Jane Doe", poster_headline="Hiring Manager",
               text="We are hiring an ML Engineer!", posted_at="2026-08-06",
               keyword="hiring ML engineer", fit_score=fit, fetched_at=fetched_at)
    base.update(kw)
    return base


def test_upsert_dedups_on_url(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc).isoformat()
    upsert_hiring_post(conn, _post("https://li/posts/1", 0.5, now))
    upsert_hiring_post(conn, _post("https://li/posts/1", 0.9, now))  # same url
    rows = hiring_posts(conn, within_hours=24)
    assert len(rows) == 1 and rows[0]["fit_score"] == 0.9


def test_list_orders_by_fit_and_filters_window(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    upsert_hiring_post(conn, _post("u1", 0.3, now.isoformat(), text="Hiring a data scientist"))
    upsert_hiring_post(conn, _post("u2", 0.8, now.isoformat()))
    old = (now - timedelta(hours=48)).isoformat()
    upsert_hiring_post(conn, _post("u3", 0.99, old))  # outside 24h window
    rows = hiring_posts(conn, within_hours=24)
    assert [r["url"] for r in rows] == ["u2", "u1"]  # u3 filtered out, sorted by fit


def test_dismissed_survives_reupsert(tmp_path):
    # A re-fetched post the user already dismissed must stay hidden.
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc).isoformat()
    upsert_hiring_post(conn, _post("https://li/posts/1", 0.5, now))
    dismiss_hiring_post(conn, hiring_posts(conn, within_hours=24)[0]["id"])
    upsert_hiring_post(conn, _post("https://li/posts/1", 0.9, now))  # same url, re-fetched
    assert hiring_posts(conn, within_hours=24) == []  # still hidden


def test_dismiss_hides_post(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc).isoformat()
    upsert_hiring_post(conn, _post("u1", 0.5, now))
    pid = hiring_posts(conn, within_hours=24)[0]["id"]
    dismiss_hiring_post(conn, pid)
    assert hiring_posts(conn, within_hours=24) == []


def test_status_sorts_done_posts_last_and_survives_refetch(tmp_path):
    import pytest
    from job_dashboard.db_hiring import set_hiring_status, contacted_elsewhere
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc).isoformat()
    upsert_hiring_post(conn, _post("hi", 0.9, now, text="Hiring A, mail x@acme.ai"))
    upsert_hiring_post(conn, _post("lo", 0.2, now, text="Hiring B"))
    ids = {r["url"]: r["id"] for r in hiring_posts(conn, within_hours=24)}
    set_hiring_status(conn, ids["hi"], "emailed")
    rows = hiring_posts(conn, within_hours=24)
    assert [r["url"] for r in rows] == ["lo", "hi"]               # done post sinks despite the higher fit
    assert rows[1]["status"] == "emailed" and rows[1]["status_at"]
    upsert_hiring_post(conn, _post("hi", 0.95, now, text="Hiring A, mail x@acme.ai"))   # re-fetched
    assert {r["url"]: r["status"] for r in hiring_posts(conn, within_hours=24)}["hi"] == "emailed"
    set_hiring_status(conn, ids["hi"], "applied", only_if_unset=True)           # auto-mark never overwrites
    assert {r["url"]: r["status"] for r in hiring_posts(conn, within_hours=24)}["hi"] == "emailed"
    assert contacted_elsewhere(conn, ids["lo"], "X@acme.ai")[0]["id"] == ids["hi"]
    set_hiring_status(conn, ids["hi"], None)
    assert hiring_posts(conn, within_hours=24)[0]["url"] == "hi"                # cleared → back on top
    with pytest.raises(ValueError):
        set_hiring_status(conn, ids["hi"], "sent")
