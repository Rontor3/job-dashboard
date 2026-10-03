from fastapi.testclient import TestClient

from job_dashboard import tracker
from job_dashboard.api.app import create_app
from job_dashboard.apply import queue as q
from job_dashboard.db import dashboard_stats, init_db, insert_job, set_job_status
from job_dashboard.models import JobListing


def _db(tmp_path, companies):
    path = str(tmp_path / "t.db")
    conn = init_db(path)
    for i, co in enumerate(companies):
        insert_job(conn, JobListing(source="s", title="DS", company=co, job_url=f"http://x/{i}", description="d"))
    conn.commit()
    return path, conn, {r[1]: r[0] for r in conn.execute("SELECT id, company FROM jobs")}


def test_failed_bucket_carries_the_queue_reason(tmp_path):
    _, conn, ids = _db(tmp_path, ["Acme", "Globex"])
    set_job_status(conn, ids["Acme"], "failed")
    q.enqueue(conn, ids["Acme"])
    q.mark(conn, ids["Acme"], "parked", "needs_answers")
    set_job_status(conn, ids["Globex"], "saved")
    q.enqueue(conn, ids["Globex"])
    board = tracker.tracker_jobs(conn)
    acme = board["failed"][0]
    assert (acme["company"], acme["queue_state"], acme["queue_reason"]) == ("Acme", "parked", "needs_answers")
    assert board["saved"][0]["queue_state"] == "queued"


def test_interview_round_is_set_with_the_status_and_cleared_otherwise(tmp_path):
    _, conn, ids = _db(tmp_path, ["Acme"])
    tracker.set_status(conn, ids["Acme"], "interviewing", round=2)
    assert tracker.tracker_jobs(conn)["interviewing"][0]["interview_round"] == 2
    tracker.set_status(conn, ids["Acme"], "interviewing")              # no round given -> round 1
    assert tracker.tracker_jobs(conn)["interviewing"][0]["interview_round"] == 1
    tracker.set_status(conn, ids["Acme"], "offer")
    assert tracker.tracker_jobs(conn)["offer"][0]["interview_round"] is None


def test_round_must_be_positive(tmp_path):
    _, conn, ids = _db(tmp_path, ["Acme"])
    try:
        tracker.set_status(conn, ids["Acme"], "interviewing", round=0)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_stats_count_failed(tmp_path):
    _, conn, ids = _db(tmp_path, ["Acme", "Globex"])
    set_job_status(conn, ids["Acme"], "failed")
    assert dashboard_stats(conn)["failed"] == 1


def test_patch_status_api_accepts_failed_and_round(tmp_path):
    path, conn, ids = _db(tmp_path, ["Acme"])
    c = TestClient(create_app(db_path=path))
    r = c.patch(f"/api/jobs/{ids['Acme']}/status", json={"status": "interviewing", "round": 3})
    assert r.status_code == 200
    assert c.get("/api/tracker").json()["interviewing"][0]["interview_round"] == 3
    assert c.patch(f"/api/jobs/{ids['Acme']}/status", json={"status": "failed"}).status_code == 200
    assert c.patch(f"/api/jobs/{ids['Acme']}/status", json={"status": "interviewing", "round": 0}).status_code == 422
