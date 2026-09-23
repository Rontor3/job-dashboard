"""Unit tests for RateLimiter."""
import pytest
from career_agent.reliability.rate_limiter import RateLimiter, domain_key, map_outcome


@pytest.fixture
def rl(tmp_path):
    return RateLimiter(pace="fast", domain_day_cap=3, hour_cap=5,
                       state_path=tmp_path / "portal_state.json")


def test_fresh_domain_ok(rl):
    assert rl.check("greenhouse.io") == "ok"


def test_domain_cap_triggers_defer(rl):
    for _ in range(3):
        rl.record("greenhouse.io", "dry_run")
    assert rl.check("greenhouse.io") == "defer"


def test_hourly_cap_triggers_defer(rl):
    for _ in range(5):
        rl.record("greenhouse.io", "dry_run")
    # hourly cap hit — even a different domain is deferred
    assert rl.check("lever.co") == "defer"


def test_captcha_triggers_cooldown(rl):
    rl.record("greenhouse.io", "captcha")
    result = rl.check("greenhouse.io")
    assert result.startswith("cooldown_until:")


def test_domain_key_strips_prefix():
    assert domain_key("https://jobs.greenhouse.io/anthropic/123") == "greenhouse.io"
    assert domain_key("https://careers.lever.co/company/job") == "lever.co"
    assert domain_key("https://www.linkedin.com/jobs/view/123") == "linkedin.com"
    assert domain_key("https://apply.workable.com/company/j/ABC") == "workable.com"


def test_map_outcome_captcha():
    assert map_outcome("gate:captcha") == "captcha"
    assert map_outcome("gate:hcaptcha") == "captcha"
    assert map_outcome("gate:cloudflare_interstitial") == "blocked"
    assert map_outcome("reached_submit_dry_run") == "dry_run"
    assert map_outcome("submitted") == "submitted"
    assert map_outcome("unknown_thing") == "error"
