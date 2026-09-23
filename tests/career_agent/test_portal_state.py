"""Unit tests for PortalState."""
import time
import pathlib
import pytest
from career_agent.reliability.portal_state import PortalState


@pytest.fixture
def ps(tmp_path):
    return PortalState(path=tmp_path / "portal_state.json")


def test_new_domain_is_blank(ps):
    e = ps.get("greenhouse.io")
    assert e["apps_today"] == 0
    assert e["escalation_count"] == 0
    assert e["cooldown_until"] is None


def test_normalisation(ps):
    ps.record_outcome("jobs.greenhouse.io", "submitted")
    e = ps.get("greenhouse.io")
    assert e["apps_today"] == 1


def test_submitted_increments_and_resets(ps):
    ps.record_outcome("greenhouse.io", "captcha")
    ps.record_outcome("greenhouse.io", "submitted")
    e = ps.get("greenhouse.io")
    assert e["apps_today"] == 1
    assert e["escalation_count"] == 0
    assert e["cooldown_until"] is None


def test_captcha_sets_cooldown(ps):
    ps.record_outcome("greenhouse.io", "captcha")
    assert ps.is_cooling("greenhouse.io")


def test_captcha_doubles_cooldown(ps):
    ps.record_outcome("greenhouse.io", "captcha")
    e1 = ps.get("greenhouse.io")
    ts1 = e1["cooldown_until"]

    # Force escalation_count to 2 by recording another captcha
    ps.record_outcome("greenhouse.io", "captcha")
    e2 = ps.get("greenhouse.io")
    assert e2["escalation_count"] == 2
    # Second cooldown should be further in the future than the first
    from datetime import datetime, timezone
    t1 = datetime.fromisoformat(ts1).timestamp()
    t2 = datetime.fromisoformat(e2["cooldown_until"]).timestamp()
    assert t2 > t1


def test_submitted_clears_captcha_escalation(ps):
    ps.record_outcome("greenhouse.io", "captcha")
    ps.record_outcome("greenhouse.io", "captcha")
    ps.record_outcome("greenhouse.io", "submitted")
    assert not ps.is_cooling("greenhouse.io")
    assert ps.get("greenhouse.io")["escalation_count"] == 0


def test_daily_reset(ps):
    # Manually set a past date to simulate day rollover
    import json
    data = {"greenhouse.io": {
        "apps_today": 5, "apps_today_date": "2020-01-01",
        "apps_total": 5, "escalation_count": 0,
        "cooldown_until": None, "cooldown_base_s": 3600, "last_run": None,
    }}
    ps._path.write_text(json.dumps(data))
    e = ps.get("greenhouse.io")
    assert e["apps_today"] == 0


def test_reset_cooldown(ps):
    ps.record_outcome("greenhouse.io", "captcha")
    assert ps.is_cooling("greenhouse.io")
    ps.reset_cooldown("greenhouse.io")
    assert not ps.is_cooling("greenhouse.io")


def test_error_outcome_no_change(ps):
    ps.record_outcome("greenhouse.io", "error")
    e = ps.get("greenhouse.io")
    assert e["apps_today"] == 0
    assert e["escalation_count"] == 0
