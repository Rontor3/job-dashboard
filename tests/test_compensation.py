import pytest

from job_dashboard.match.compensation import (
    parse_ctc_lpa, find_ctc_lpa_in_jd, job_ctc_lpa,
)


@pytest.mark.parametrize("text,expected", [
    ("₹50L – ₹55L", 55),
    ("₹30L – ₹40L", 40),
    ("25-35 LPA", 35),
    ("30 LPA", 30),
    ("100000-150000 USD", pytest.approx(150000 * 83 / 1e5, rel=0.01)),   # ~124.5
    ("$150k - $230k", pytest.approx(230000 * 83 / 1e5, rel=0.01)),       # ~190.9
    ("₹2500000 P.A.", 25.0),
])
def test_parse_ctc_reasonable(text, expected):
    assert parse_ctc_lpa(text) == expected


@pytest.mark.parametrize("text", [
    "$90 - $150 /hour",   # hourly → unknown
    "70-90 USD",          # junk (≈0.07 LPA) → unknown
    "₹30,000 – ₹35,000",  # bare small ₹ (monthly? stipend?) → ambiguous
    "Not disclosed",
    "",
    None,
])
def test_parse_ctc_returns_none_when_unsure(text):
    assert parse_ctc_lpa(text) is None


def test_jd_lpa_only_not_lakh_users():
    assert find_ctc_lpa_in_jd("CTC: 22 LPA for the right candidate") == 22
    assert find_ctc_lpa_in_jd("Serving 10 lakh users across India") is None  # not pay
    assert job_ctc_lpa(None, "Package is 18-24 LPA depending on experience") == 24


def test_sweep_hides_below_ctc_floor(tmp_path):
    from datetime import datetime, timezone
    from job_dashboard.db import (
        init_db, insert_job, upsert_embed_score, record_llm_evaluation, query_jobs,
    )
    from job_dashboard.models import JobListing
    from job_dashboard.match.liveness import sweep

    conn = init_db(str(tmp_path / "t.db"))
    fresh = datetime.now(timezone.utc).isoformat()

    def seed(url, salary, desc, llm=70):
        insert_job(conn, JobListing(source="naukri", external_id=None, title="Data Scientist",
                                    company="Co", location="R", description=desc, job_url=url,
                                    job_type=None, is_remote=False, salary_text=salary,
                                    posted_date=fresh))
        jid = conn.execute("SELECT id FROM jobs WHERE job_url = ?", (url,)).fetchone()[0]
        upsert_embed_score(conn, jid, 0.6, "h")
        record_llm_evaluation(conn, jid, llm, "Good Fit", [], [], {})
        conn.commit()
        return jid

    low = seed("u/low", "₹18L – ₹22L", "d")        # 22 LPA < 25 → hidden
    ok = seed("u/ok", "₹30L – ₹40L", "d")          # 40 LPA → kept
    jd_low = seed("u/jdlow", None, "CTC 12 LPA")    # from JD, < 25 → hidden
    unknown = seed("u/unk", None, "Great role, apply now")  # no CTC → kept

    counts = sweep(conn, http_fetch=lambda u: (200, "apply now"), min_ctc_lpa=25)
    assert counts["low-ctc"] == 2

    visible = {j["id"] for j in query_jobs(conn, limit=50)[0]}
    assert low not in visible and jd_low not in visible
    assert ok in visible and unknown in visible
