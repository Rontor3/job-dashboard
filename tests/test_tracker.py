from fastapi.testclient import TestClient
from job_dashboard.api.app import create_app
from job_dashboard.db import init_db, insert_job, set_job_status, upsert_company_classification, dashboard_stats
from job_dashboard.models import JobListing


def _job(company, url, title="DS"):
    return JobListing(source="test", external_id=None, title=title, company=company,
                      location="Remote", description="d", job_url=url, job_type=None,
                      is_remote=False, salary_text=None, posted_date=None)


def _seed(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    for i, (co, st) in enumerate([("Acme", "saved"), ("Globex", "applied"),
                                  ("Initech", "interviewing"), ("Umbrella", "offer"),
                                  ("Soylent", "rejected"), ("Wonka", None)]):
        insert_job(conn, _job(co, f"http://x/{i}"))
    conn.commit()
    ids = {r[1]: r[0] for r in conn.execute("SELECT id, company FROM jobs")}
    for co, st in [("Acme","saved"),("Globex","applied"),("Initech","interviewing"),
                   ("Umbrella","offer"),("Soylent","rejected")]:
        set_job_status(conn, ids[co], st)
    upsert_company_classification(conn, "acme", "BFSI", "Product", "dict")
    conn.commit(); conn.close()
    return str(tmp_path / "t.db")


def test_tracker_groups_by_stage(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path)))
    board = client.get("/api/tracker").json()
    assert [j["company"] for j in board["saved"]] == ["Acme"]
    assert board["saved"][0]["industry"] == "BFSI"        # carries chips
    assert [j["company"] for j in board["applied"]] == ["Globex"]
    assert [j["company"] for j in board["offer"]] == ["Umbrella"]
    assert [j["company"] for j in board["archived"]] == ["Soylent"]   # rejected -> archived
    assert all(j["company"] != "Wonka" for b in board.values() for j in b)  # untracked excluded


def test_stats_has_verdicts_and_industries(tmp_path):
    conn = init_db(str(tmp_path / "s.db"))
    insert_job(conn, _job("Acme", "http://x/1")); conn.commit()
    upsert_company_classification(conn, "acme", "BFSI", "Product", "dict")
    s = dashboard_stats(conn)
    assert "verdict_counts" in s and isinstance(s["verdict_counts"], dict)
    assert "top_industries" in s and isinstance(s["top_industries"], list)
