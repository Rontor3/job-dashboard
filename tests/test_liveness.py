from datetime import datetime, timezone, timedelta

from job_dashboard.db import (
    init_db, insert_job, upsert_embed_score, record_llm_evaluation, query_jobs,
)
from job_dashboard.match.liveness import is_bad_fit, http_liveness, sweep
from job_dashboard.models import JobListing


def _job(source, url, title, posted):
    return JobListing(source=source, external_id=None, title=title, company="Co",
                      location="Remote", description="d", job_url=url, job_type=None,
                      is_remote=False, salary_text=None, posted_date=posted)


def _seed(conn, source, url, title, posted, verdict=None, llm=None):
    insert_job(conn, _job(source, url, title, posted))
    jid = conn.execute("SELECT id FROM jobs WHERE job_url = ?", (url,)).fetchone()[0]
    if verdict is not None or llm is not None:
        upsert_embed_score(conn, jid, 0.5, "h")  # llm eval requires an embed score first
        record_llm_evaluation(conn, jid, llm if llm is not None else 50,
                              verdict or "Good Fit", [], [], {})
    conn.commit()
    return jid


# --- pure helpers --------------------------------------------------------
def test_is_bad_fit():
    assert is_bad_fit({"verdict": "Poor Fit", "title": "Data Scientist"})
    assert is_bad_fit({"verdict": "Good Fit", "title": "Graphic Designer"})  # nuisance
    assert not is_bad_fit({"verdict": "Strong Fit", "title": "ML Engineer"})


def test_http_liveness_states():
    assert http_liveness("http://x/1", fetch=lambda u: (404, "")) is False
    assert http_liveness("http://x/1", fetch=lambda u: (200, "No longer accepting applications")) is False
    assert http_liveness("http://x/1", fetch=lambda u: (200, "Apply now, great role")) is True
    assert http_liveness("http://x/1", fetch=lambda u: (503, "")) is None
    assert http_liveness("http://x/1", fetch=lambda u: (_ for _ in ()).throw(OSError())) is None


# --- the sweep -----------------------------------------------------------
def test_sweep_hides_badfit_stale_closed_and_respects_browser_gate(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    fresh = now.isoformat()
    old = (now - timedelta(days=90)).isoformat()

    good = _seed(conn, "remoteok", "http://ok/live", "ML Engineer", fresh, "Strong Fit", 88)
    bad = _seed(conn, "remoteok", "http://ok/bad", "Graphic Designer", fresh, "Good Fit", 70)
    stale = _seed(conn, "jobspy:indeed", "http://ok/old", "Data Scientist", old, "Good Fit", 60)
    closed = _seed(conn, "remoteok", "http://ok/closed", "ML Engineer", fresh, "Good Fit", 75)
    li_hi = _seed(conn, "jobspy:linkedin", "https://www.linkedin.com/jobs/view/1/", "ML Engineer", fresh, "Strong Fit", 80)
    li_lo = _seed(conn, "jobspy:linkedin", "https://www.linkedin.com/jobs/view/2/", "ML Engineer", fresh, "Weak Fit", 30)

    def http_fetch(url):
        return (200, "closed: applications are closed") if url.endswith("/closed") else (200, "Apply now")

    browser_calls = []
    def browser_check(url):
        browser_calls.append(url)
        return False  # say every browser-checked job is closed

    counts = sweep(conn, http_fetch=http_fetch, browser_check=browser_check,
                   llm_gate=50, max_age_days=45, now=now)

    assert counts["bad-fit"] == 1 and counts["stale"] == 1 and counts["closed"] >= 2
    # browser only used for the high-llm LinkedIn job, not the low one
    assert browser_calls == ["https://www.linkedin.com/jobs/view/1/"]

    visible = {j["id"] for j in query_jobs(conn, limit=100)[0]}
    assert good in visible                       # live good-fit stays
    assert bad not in visible and stale not in visible and closed not in visible
    assert li_hi not in visible                  # browser said closed
    assert li_lo in visible                      # below gate → left alone
