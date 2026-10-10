"""Details per company (set once, seen by every opening there) and questions only some of your jobs ask."""
from fastapi.testclient import TestClient

from job_dashboard import changes, situational
from job_dashboard.api.app import create_app
from job_dashboard.db import get_job, init_db, insert_job, query_jobs
from job_dashboard.models import JobListing


def _job(n, company="Acme", title="ML Engineer", location="Bengaluru", description="Build models."):
    return JobListing(source="linkedin", title=title, company=company, location=location, description=description,
                      job_url=f"https://x/{n}", external_id=str(n))


def _status(conn, jid, status="saved"):
    conn.execute("UPDATE jobs SET status=? WHERE id=?", (status, jid))
    conn.commit()


def test_company_details_reach_every_opening_and_undo(tmp_path):
    p = str(tmp_path / "j.db")
    conn = init_db(p)
    for n in (1, 2):
        insert_job(conn, _job(n, company="Acme Corp" if n == 1 else "  acme   corp "))
    a, b = (j["id"] for j in query_jobs(conn)[0])
    c = TestClient(create_app(db_path=p))
    r = c.put("/api/company-details", json={"company": "Acme Corp", "details": {"referrer": " Jane ", "applied_before": True}})
    assert r.json()["details"] == {"referrer": "Jane", "applied_before": True}
    assert get_job(conn, a)["apply_details"]["referrer"] == "Jane"
    assert get_job(conn, b)["apply_details"]["applied_before"] is True                  # same company, other spacing
    c.put(f"/api/jobs/{b}/apply-details", json={"referrer": "Raj"})
    assert get_job(conn, b)["apply_details"]["referrer"] == "Raj"                        # the job's own value wins
    assert get_job(conn, b)["apply_details"]["applied_before"] is True                   # the company fills the rest
    assert list(c.get("/api/company-details").json()["companies"]) == ["acme corp"]
    last = conn.execute("SELECT id FROM change_log WHERE entity='company' ORDER BY id DESC").fetchone()[0]
    changes.undo(conn, last)
    assert get_job(conn, a)["apply_details"] == {}


def test_a_japan_job_asks_for_jlpt_and_says_why(tmp_path, fake_embed):
    p = str(tmp_path / "j.db")
    conn = init_db(p)
    insert_job(conn, _job(1, company="Mercari", location="Tokyo, Japan"))
    insert_job(conn, _job(2, company="Acme"))
    insert_job(conn, _job(3, company="Pentagon Labs", description="Security clearance required."))
    for j in query_jobs(conn)[0]:
        _status(conn, j["id"])
    _status(conn, [j for j in query_jobs(conn)[0] if j["company"] == "Pentagon Labs"][0]["id"], "rejected")
    ids = {a["id"] for a in situational.active(conn)}
    assert "jlpt_level" in ids and "security_clearance" not in ids                       # a rejected job asks nothing
    c = TestClient(create_app(db_path=p, qa_embed=fake_embed))
    bank = {b["id"]: b for b in c.get("/api/inbox", params={"bank_limit": 50}).json()["bank"]}
    assert bank["jlpt_level"]["why"] == "1 of your jobs is in Japan or asks for Japanese (Mercari)."
    assert "N2" in bank["jlpt_level"]["options"]
    r = c.get("/api/profile/readiness").json()
    assert {"key": "qbank:jlpt_level", "label": "Japanese (JLPT)", "why": bank["jlpt_level"]["why"]} in r["optional_missing"]
    c.post("/api/profile/facts", json={"answers": {"qbank:jlpt_level": "N2"}})
    assert "jlpt_level" not in {b["id"] for b in c.get("/api/inbox", params={"bank_limit": 50}).json()["bank"]}
