import pytest
from career_agent.integrations.live_view.token import (
    mint_token, check_and_consume, is_valid, build_url,
)


def test_is_valid_allows_reconnect_but_respects_expiry_and_revoke():
    t = mint_token(300, now=1000.0)
    # reconnect-friendly: valid repeatedly within the TTL (does NOT consume)
    assert is_valid(t, t.value, now=1001.0) is True
    assert is_valid(t, t.value, now=1002.0) is True
    # wrong token / expired / revoked all fail
    assert is_valid(t, "nope", now=1003.0) is False
    assert is_valid(t, t.value, now=1400.0) is False   # past TTL
    t.used = True                                       # revoked on close
    assert is_valid(t, t.value, now=1004.0) is False


def test_token_is_high_entropy_and_unique():
    a = mint_token(300, now=1000.0)
    b = mint_token(300, now=1000.0)
    assert len(a.value) >= 43 and a.value != b.value


def test_single_use():
    t = mint_token(300, now=1000.0)
    assert check_and_consume(t, t.value, now=1001.0) is True
    assert check_and_consume(t, t.value, now=1002.0) is False  # already used


def test_expiry():
    t = mint_token(300, now=1000.0)
    assert check_and_consume(t, t.value, now=1400.0) is False  # > ttl


def test_wrong_token_rejected():
    t = mint_token(300, now=1000.0)
    assert check_and_consume(t, "nope", now=1001.0) is False
    assert t.used is False


def test_build_url_tailnet_default():
    url = build_url("mac.tailnet.ts.net", 8765, "abc", allow_public=False)
    assert url == "http://mac.tailnet.ts.net:8765/s/abc"


def test_build_url_requires_host_when_not_public():
    with pytest.raises(ValueError):
        build_url(None, 8765, "abc", allow_public=False)


def test_build_url_accepts_tailnet_ip():
    assert build_url("100.101.102.103", 8765, "abc", allow_public=False) == \
        "http://100.101.102.103:8765/s/abc"


def test_build_url_rejects_public_host_without_optin():
    with pytest.raises(ValueError):
        build_url("foo.trycloudflare.com", 8765, "abc", allow_public=False)


def test_build_url_allows_public_host_with_optin():
    assert build_url("foo.trycloudflare.com", 8765, "abc", allow_public=True) == \
        "http://foo.trycloudflare.com:8765/s/abc"


def test_build_url_still_requires_host_even_when_public():
    with pytest.raises(ValueError):
        build_url(None, 8765, "abc", allow_public=True)
