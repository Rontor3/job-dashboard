"""Marking a job the agent left for you as Applied counts as your hand submit on that site (first-submit rule)."""
from fastapi.testclient import TestClient

from job_dashboard import autonomy
from job_dashboard.api.app import create_app
from job_dashboard.apply import queue as q
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing


def _app(tmp_path, fake_embed):
    db = str(tmp_path / "t.db")
    c = init_db(db)
    for i, url in enumerate(["https://www.iimjobs.com/j/ds-1", "https://www.iimjobs.com/j/ds-2"], 1):
        insert_job(c, JobListing(source="iimjobs", title=f"DS {i}", company="X", job_url=url, description="jd"))
    q.ensure(c)
    q.enqueue(c, 1)
    q.mark(c, 1, "parked", "one_click_needs_autosubmit")
    c.close()
    return TestClient(create_app(db_path=db, qa_embed=fake_embed, queue_launch=lambda *a: 0)), db


def test_marking_a_parked_job_applied_satisfies_the_first_submit_on_that_site(tmp_path, fake_embed):
    c, db = _app(tmp_path, fake_embed)
    key = autonomy.ats_key("https://www.iimjobs.com/j/ds-2")
    assert not autonomy.has_confirmed_submit(init_db(db), key)
    assert c.patch("/api/jobs/1/status", json={"status": "applied"}).status_code == 200
    assert autonomy.has_confirmed_submit(init_db(db), key)          # another iimjobs job may now go on its own
    c.patch("/api/jobs/1/status", json={"status": "applied"})
    assert init_db(db).execute("SELECT count(*) FROM submit_history WHERE job_id=1").fetchone()[0] == 1   # once


def test_a_job_the_agent_never_touched_is_not_counted(tmp_path, fake_embed):
    c, db = _app(tmp_path, fake_embed)
    c.patch("/api/jobs/2/status", json={"status": "applied"})
    assert init_db(db).execute("SELECT count(*) FROM submit_history").fetchone()[0] == 0
