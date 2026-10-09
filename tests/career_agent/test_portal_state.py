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


def test_captcha_doubles_cooldown(ps):
    from datetime import datetime
    def left():
        return datetime.fromisoformat(ps.get("greenhouse.io")["cooldown_until"]).timestamp() - time.time()
    ps.record_outcome("greenhouse.io", "captcha")
    first = left()
    ps.record_outcome("greenhouse.io", "captcha")
    assert ps.get("greenhouse.io")["escalation_count"] == 2
    assert left() == pytest.approx(2 * first, abs=5)


def test_blocked_cools_down_twice_as_long_as_a_captcha(ps):
    from datetime import datetime
    ps.record_outcome("greenhouse.io", "blocked")
    left = datetime.fromisoformat(ps.get("greenhouse.io")["cooldown_until"]).timestamp() - time.time()
    assert ps.is_cooling("greenhouse.io") and left == pytest.approx(7200, abs=5)


def test_daily_reset(tmp_path):
    import json
    path = tmp_path / "portal_state.json"
    path.write_text(json.dumps({"greenhouse.io": {
        "apps_today": 5, "apps_today_date": "2020-01-01",
        "apps_total": 5, "escalation_count": 0,
        "cooldown_until": None, "cooldown_base_s": 3600, "last_run": None,
    }}))
    e = PortalState(path=path).get("greenhouse.io")
    assert e["apps_today"] == 0 and e["apps_total"] == 5


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
