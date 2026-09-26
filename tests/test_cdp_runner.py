import sqlite3
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
