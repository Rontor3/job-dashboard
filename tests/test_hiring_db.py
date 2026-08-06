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
    upsert_hiring_post(conn, _post("u1", 0.3, now.isoformat()))
    upsert_hiring_post(conn, _post("u2", 0.8, now.isoformat()))
    old = (now - timedelta(hours=48)).isoformat()
    upsert_hiring_post(conn, _post("u3", 0.99, old))  # outside 24h window
    rows = hiring_posts(conn, within_hours=24)
    assert [r["url"] for r in rows] == ["u2", "u1"]  # u3 filtered out, sorted by fit


def test_dismiss_hides_post(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc).isoformat()
    upsert_hiring_post(conn, _post("u1", 0.5, now))
    pid = hiring_posts(conn, within_hours=24)[0]["id"]
    dismiss_hiring_post(conn, pid)
    assert hiring_posts(conn, within_hours=24) == []
