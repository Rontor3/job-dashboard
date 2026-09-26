from job_dashboard.db import init_db
from job_dashboard.models import JobListing
from job_dashboard.pipeline import run_pipeline
from job_dashboard.api.refresh_job import _summarize
from job_dashboard.sources.cdp.types import SiteResult


def L(i):
    return JobListing(source="linkedin", title=f"t{i}", company="c", job_url=f"https://l/{i}",
                      description="d", external_id=str(i), apply_kind="native")


def _run(conn, bf):
    return run_pipeline(conn, [], [], browser_fetch=bf,
                        model_loader=lambda: (_ for _ in ()).throw(RuntimeError("no model")))


def test_browser_listings_are_inserted_and_counted(tmp_path):
    conn = init_db(str(tmp_path / "j.db"))
    r = _run(conn, lambda c: ([L(1), L(2)], [SiteResult("linkedin", mode="backfill", new=2)]))
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
    assert r["browser"][0]["site"] == "linkedin" and r["browser"][0]["new"] == 2


def test_duplicate_url_not_counted_as_new(tmp_path):
    conn = init_db(str(tmp_path / "j.db"))
    _run(conn, lambda c: ([L(1)], [SiteResult("linkedin", new=1)]))
    r = _run(conn, lambda c: ([L(1)], [SiteResult("linkedin", new=1)]))
    assert r["browser"][0]["new"] == 0


def test_browser_failure_never_aborts_pipeline(tmp_path):
    conn = init_db(str(tmp_path / "j.db"))
    def boom(c): raise RuntimeError("chrome exploded")
    r = _run(conn, boom)
    assert "chrome exploded" in r["browser"][0]["note"] and "ingest" in r


def test_no_browser_fetch_means_no_key_change_needed(tmp_path):
    conn = init_db(str(tmp_path / "j.db"))
    assert _run(conn, None)["browser"] == []


def test_summarize_lists_each_site():
    s = _summarize({"ingest": {"new_jobs": 3}, "embed_scored": 3,
                    "browser": [{"site": "linkedin", "new": 12, "note": ""}, {"site": "naukri", "new": 0, "note": "not due"}]})
    assert "linkedin +12" in s and "naukri: not due" in s
