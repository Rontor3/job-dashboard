import pytest
from fastapi.testclient import TestClient

from job_dashboard import change_entities, notifications
from job_dashboard.api.app import create_app
from job_dashboard.api.notification_routes import TEMPLATE, add_fact, parse
from job_dashboard.apply.queue_runner import announce
from job_dashboard.db import init_db, insert_job, set_job_status
from job_dashboard.models import JobListing
from job_dashboard.worker import announce_refresh

AGENT = {"X-Agent-Session": "s1", "X-Agent-Message": "m1"}


@pytest.fixture
def env(tmp_path, monkeypatch, fake_embed):
    db = str(tmp_path / "jobs.db")
    c = init_db(db)
    for i in range(3):
        insert_job(c, JobListing(source="s", title=f"Engineer {i}", company="Acme", job_url=f"https://x/{i}", description="jd"))
    c.close()
    monkeypatch.setitem(change_entities.FILES, "about_me", lambda: tmp_path / "agent" / "about-me.md")
    return TestClient(create_app(db_path=db, qa_embed=fake_embed)), db, tmp_path


def test_feed_newest_first_dedupe_read_and_dismiss(env):
    c, db, _ = env
    conn = init_db(db)
    first = notifications.notify(conn, "parked", "Engineer 0 needs answers", level="action", job_id=1, dedupe="run:1")
    notifications.notify(conn, "matches", "3 strong new matches", data={"job_ids": [1, 2]})
    notifications.notify(conn, "submitted", "Applied: Engineer 0", level="success", job_id=1, dedupe="run:1")
    conn.close()
    feed = c.get("/api/notifications").json()
    assert [i["title"] for i in feed["items"]] == ["Applied: Engineer 0", "3 strong new matches"]   # run:1 replaced
    assert feed["unread"] == 2 and feed["items"][1]["data"] == {"job_ids": [1, 2]}
    assert all(i["id"] != first for i in feed["items"])
    newest = feed["items"][0]["id"]
    assert c.post("/api/notifications/read", json={"ids": [newest]}).json() == {"marked": 1, "unread": 1}
    assert c.post(f"/api/notifications/{newest}/dismiss").json()["unread"] == 1
    assert c.post(f"/api/notifications/{newest}/dismiss").status_code == 404
    assert c.post("/api/notifications/read", json={}).json()["unread"] == 0


def test_agent_can_notify_without_confirmation(env):
    c, *_ = env
    r = c.post("/api/notifications", json={"title": "Shortlist ready", "body": "12 jobs", "level": "action",
                                           "job_ids": [1, 2]}, headers=AGENT)
    assert r.status_code == 200
    item = c.get("/api/notifications").json()["items"][0]
    assert (item["kind"], item["source"], item["data"]) == ("agent", "agent", {"job_ids": [1, 2]})
    assert c.post("/api/notifications", json={"title": "x", "level": "loud"}).status_code == 422


def test_runs_announce_what_happened(env):
    _, db, _ = env
    conn = init_db(db)
    announce(conn, 1, "parked", "needs_answers")
    announce(conn, 2, "failed", "crashed")
    announce(conn, 1, "done", "submitted")
    items = notifications.listing(conn)
    conn.close()
    assert [(i["kind"], i["level"]) for i in items] == [("submitted", "success"), ("failed", "warning")]
    assert items[0]["title"] == "Applied: Engineer 0 at Acme"


def test_refresh_announces_strong_new_matches(env):
    _, db, _ = env
    conn = init_db(db)
    conn.execute("INSERT INTO match_scores (job_id, embed_score, profile_hash, scored_at) VALUES (1, 0.9, 'h', 'x'), "
                 "(2, 0.4, 'h', 'x')")
    conn.commit()
    conn.close()
    announce_refresh(db, "2000-01-01", {"ingest": {"new_jobs": 3}})
    conn = init_db(db)
    item = notifications.listing(conn)[0]
    conn.close()
    assert item["title"] == "1 strong new match" and item["data"] == {"job_ids": [1]}


def test_batch_queue_skips_applied_and_needs_confirm_from_the_agent(env):
    c, db, _ = env
    conn = init_db(db)
    set_job_status(conn, 3, "applied")
    conn.close()
    r = c.post("/api/queue/batch", json={"job_ids": [2, 1, 3, 99, 2]}).json()
    assert r["queued"] == [2, 1]
    assert [s["job_id"] for s in r["skipped"]] == [3, 99]
    assert [i["job_id"] for i in r["items"]] == [2, 1]
    assert c.post("/api/queue/batch", json={"job_ids": []}).status_code == 422
    assert c.post("/api/queue/batch", json={"job_ids": [1]}, headers=AGENT).status_code == 403


def test_add_fact_places_dedupes_and_rewords():
    text, changed = add_fact(TEMPLATE, "Target", "ML infra roles, senior")
    assert changed and parse(text)["Target"] == ["ML infra roles, senior"]
    same, changed = add_fact(text, "Preferences", "ml  infra roles, SENIOR")
    assert not changed and same == text
    text, _ = add_fact(text, "Target", "Bangalore or remote")
    text, _ = add_fact(text, "Target", "Staff ML infra roles", replaces="ML infra roles, senior")
    assert parse(text)["Target"] == ["Staff ML infra roles", "Bangalore or remote"]
    text, _ = add_fact(text, "Hobbies", "chess")
    assert parse(text)["Hobbies"] == ["chess"]
    with pytest.raises(KeyError):
        add_fact(text, "Target", "x", replaces="nothing like this")


def test_about_me_facts_are_logged_with_undo(env):
    c, _, tmp = env
    assert c.get("/api/about-me").json()["exists"] is False
    r = c.post("/api/about-me/facts", json={"section": "Constraints", "fact": "Won't relocate outside India"}, headers=AGENT)
    assert r.json()["changed"] and r.json()["sections"]["Constraints"] == ["Won't relocate outside India"]
    assert (tmp / "agent" / "about-me.md").is_file()
    assert c.post("/api/about-me/facts", json={"section": "Nope", "fact": "x y"}).status_code == 422
    assert c.post("/api/about-me/facts", json={"section": "Target", "fact": "x y", "replaces": "zzz"}).status_code == 404
    change = c.get("/api/changes", params={"session_id": "s1"}).json()["changes"][0]
    assert (change["entity"], change["entity_id"]) == ("file", "about_me")
    c.post(f"/api/changes/{change['id']}/undo")
    assert c.get("/api/about-me").json()["exists"] is False
