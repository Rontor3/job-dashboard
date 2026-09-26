import sqlite3
from datetime import datetime, timedelta, timezone
from job_dashboard import qa_store
from job_dashboard.sources.cdp import state

T0 = datetime(2026, 9, 27, 9, 0, tzinfo=timezone.utc)


def conn():
    c = sqlite3.connect(":memory:")
    state.ensure(c)
    return c


def test_disabled_by_default_and_toggle():
    c = conn()
    assert state.enabled(c, "linkedin") is False
    qa_store.set_setting(c, "browser_linkedin_enabled", "1")
    assert state.enabled(c, "linkedin") is True


def test_first_run_is_due_and_backfill():
    c = conn()
    assert state.due(c, "linkedin", now=T0) and state.mode_for(c, "linkedin") == "backfill"


def test_due_respects_48h_after_success():
    c = conn()
    state.record_run(c, "linkedin", ok=True, new=5, backfill_done=True, now=T0)
    assert not state.due(c, "linkedin", now=T0 + timedelta(hours=47))
    assert state.due(c, "linkedin", now=T0 + timedelta(hours=49))
    assert state.mode_for(c, "linkedin") == "incremental"


def test_failed_run_keeps_last_success_and_records_error():
    c = conn()
    state.record_run(c, "linkedin", ok=True, backfill_done=True, now=T0)
    state.record_run(c, "linkedin", ok=False, error="Blocked: authwall", now=T0 + timedelta(hours=60))
    row = state.get(c, "linkedin")
    assert row["last_error"] == "Blocked: authwall" and row["last_success_at"] == T0.isoformat()
    assert state.due(c, "linkedin", now=T0 + timedelta(hours=109))


def test_failed_first_run_stays_backfill():
    c = conn()
    state.record_run(c, "linkedin", ok=False, error="x", now=T0)
    assert state.mode_for(c, "linkedin") == "backfill"


def test_failure_cools_down_for_interval_from_last_run():
    c = conn()
    state.record_run(c, "linkedin", ok=True, backfill_done=True, now=T0)
    state.record_run(c, "linkedin", ok=False, error="Blocked: x", now=T0 + timedelta(hours=60))
    assert not state.due(c, "linkedin", now=T0 + timedelta(hours=61))
    assert state.due(c, "linkedin", now=T0 + timedelta(hours=109))


def test_failed_first_run_cools_down():
    c = conn()
    state.record_run(c, "linkedin", ok=False, error="x", now=T0)
    assert not state.due(c, "linkedin", now=T0 + timedelta(hours=1))
