import sqlite3
from datetime import datetime, timedelta, timezone
from job_dashboard import qa_store
from job_dashboard.models import JobListing
from job_dashboard.sources.cdp import runner, state
from job_dashboard.sources.cdp.types import Blocked
from tests.cdp_fakes import FakePage, make_session


def conn(enabled=True):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, source TEXT, external_id TEXT, job_url TEXT)")
    state.ensure(c)
    if enabled:
        qa_store.set_setting(c, "browser_linkedin_enabled", "1")
    return c


def L(i):
    return JobListing(source="linkedin", title="t", company="c", job_url=f"u{i}", description="d", external_id=str(i))


def go(c, run, **kw):
    adapters = {"linkedin": (run, ["t"])}
    return runner.fetch_browser_sources(
        c, adapters=adapters, reachable=lambda u: True,
        session_factory=lambda cap: make_session(FakePage(), max_loads=cap), **kw)


def test_disabled_site_is_silent():
    listings, results = go(conn(enabled=False), lambda s, ctx: [L(1)])
    assert listings == [] and results == []


def test_success_records_state_and_flips_to_incremental():
    c = conn(); seen = []
    def run(s, ctx):
        seen.append(ctx.mode); ctx.stats["skipped_known"] = 4; return [L(1), L(2)]
    listings, results = go(c, run)
    assert len(listings) == 2 and results[0].new == 2 and results[0].skipped_known == 4
    assert seen == ["backfill"] and state.mode_for(c, "linkedin") == "incremental"


def test_second_run_within_48h_is_not_due():
    c = conn(); go(c, lambda s, ctx: [])
    _, results = go(c, lambda s, ctx: [L(1)])
    assert results[0].note == "not due" and results[0].new == 0


def test_blocked_is_recorded_and_isolated():
    c = conn()
    def boom(s, ctx): raise Blocked("authwall")
    listings, results = go(c, boom)
    assert listings == [] and results[0].note.startswith("blocked")
    assert state.get(c, "linkedin")["last_error"].startswith("Blocked")
    assert state.mode_for(c, "linkedin") == "backfill"


def test_known_callback_checks_external_id_and_url():
    c = conn(); c.execute("INSERT INTO jobs (source, external_id, job_url) VALUES ('linkedin','7','u7')"); c.commit()
    got = {}
    def run(s, ctx): got["a"] = ctx.known("7", "x"); got["b"] = ctx.known("8", "u7"); got["c"] = ctx.known("8", "x"); return []
    go(c, run)
    assert got == {"a": True, "b": True, "c": False}


def test_cdp_down_changes_nothing():
    c = conn()
    _, results = runner.fetch_browser_sources(c, adapters={"linkedin": (lambda s, x: [], ["t"])},
                                              reachable=lambda u: False, session_factory=None)
    assert results[0].note == "Chrome CDP not reachable" and state.get(c, "linkedin") is None


T0 = datetime(2026, 9, 27, 9, 0, tzinfo=timezone.utc)


def test_capped_backfill_stays_backfill_and_notes_it():
    c = conn()
    def run(s, ctx): ctx.stats["capped"] = True; ctx.stats["pages"] = 3; return [L(1)]
    _, results = go(c, run)
    assert results[0].note == "cap reached (resumes next run)" and state.mode_for(c, "linkedin") == "backfill"


def test_backfill_with_no_results_stays_backfill():
    c = conn(); go(c, lambda s, ctx: [])
    assert state.mode_for(c, "linkedin") == "backfill"


def test_backfill_with_pages_and_no_new_jobs_completes():
    c = conn()
    def run(s, ctx): ctx.stats["pages"] = 2; return []
    go(c, run)
    assert state.mode_for(c, "linkedin") == "incremental"


def test_blocked_not_retried_immediately_and_note_has_error():
    c = conn()
    def boom(s, ctx): raise Blocked("authwall")
    go(c, boom, now=T0)
    _, results = go(c, lambda s, ctx: [L(1)], now=T0 + timedelta(hours=1))
    assert results[0].new == 0 and "not due" in results[0].note and "authwall" in results[0].note


def test_pages_is_session_loads():
    c = conn()
    def run(s, ctx): s.goto("https://x/a"); s.goto("https://x/b"); return []
    _, results = go(c, run)
    assert results[0].pages == 2


def test_incremental_window_widens_to_next_bucket_and_backfill_is_720():
    c = conn(); hours = []
    def run(s, ctx): hours.append(ctx.hours); ctx.stats["pages"] = 1; return []
    go(c, run, now=T0)                                        # backfill
    go(c, run, now=T0 + timedelta(hours=48))                  # incremental, gap 48h -> 48
    go(c, run, now=T0 + timedelta(hours=48 + 100))            # gap 100h -> 168
    assert hours == [720, 48, 168]


def test_redate_only_moves_posted_date_forward():
    c = conn(); c.execute("ALTER TABLE jobs ADD COLUMN posted_date TEXT")
    c.execute("INSERT INTO jobs (source, external_id, job_url, posted_date) VALUES ('linkedin','7','u7','2026-09-01T00:00:00+00:00')")
    c.commit(); got = {}
    def run(s, ctx):
        got["newer"] = ctx.redate("7", "u7", "2026-09-20T00:00:00+00:00")
        got["older"] = ctx.redate("7", "u7", "2026-09-10T00:00:00+00:00")
        got["missing"] = ctx.redate("8", "u8", "2026-09-20T00:00:00+00:00")
        return []
    go(c, run)
    assert got == {"newer": True, "older": False, "missing": False}
    assert c.execute("SELECT posted_date FROM jobs").fetchone()[0].startswith("2026-09-20")
