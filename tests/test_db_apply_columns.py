from job_dashboard.db import init_db, insert_job, job_detail, query_jobs
from job_dashboard.models import JobListing


def _job(**kw):
    base = dict(source="linkedin", title="ML Engineer", company="Acme", job_url="https://www.linkedin.com/jobs/view/1",
                description="d", external_id="1")
    return JobListing(**{**base, **kw})


def test_apply_fields_roundtrip(tmp_path):
    conn = init_db(str(tmp_path / "j.db"))
    assert insert_job(conn, _job(apply_url="https://acme.com/apply", apply_kind="external"))
    jobs, _ = query_jobs(conn)
    assert jobs[0]["apply_url"] == "https://acme.com/apply" and jobs[0]["apply_kind"] == "external"
    d = job_detail(conn, jobs[0]["id"])
    assert d["apply_url"] == "https://acme.com/apply" and d["apply_kind"] == "external"


def test_migration_is_idempotent_and_indexed(tmp_path):
    p = str(tmp_path / "j.db")
    init_db(p).close()
    conn = init_db(p)
    names = [r[1] for r in conn.execute("PRAGMA index_list(jobs)")]
    assert "jobs_source_ext" in names
    cols = [r[1] for r in conn.execute("PRAGMA table_info(jobs)")]
    assert cols.count("apply_url") == 1
    jobs, _ = query_jobs(conn)
    assert jobs == []


def test_india_filter_matches_country_city_and_suffix_not_us(tmp_path):
    conn = init_db(str(tmp_path / "j.db"))
    for i, loc in enumerate(["Bengaluru, Karnataka, India", "KA, IN", "Pune", "Remote, US", "London, UK", None]):
        insert_job(conn, _job(job_url=f"https://x/{i}", external_id=str(i), location=loc))
    jobs, total = query_jobs(conn, india=True)
    assert sorted(j["location"] for j in jobs) == ["Bengaluru, Karnataka, India", "KA, IN", "Pune"] and total == 3
    assert query_jobs(conn)[1] == 6
