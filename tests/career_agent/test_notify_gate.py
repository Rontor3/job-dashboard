from career_agent.orchestrator.graph import _notify_gate
import career_agent.browser.credential_provider as cp


def test_notify_gate_no_on_link_configured():
    # Telegram not wired at all (e.g. --no-telegram) -> never attempted.
    result = _notify_gate({}, "otp_sms", "msg")
    assert result == {"attempted": False, "sent": False}


def test_notify_gate_on_link_succeeds():
    seen = []
    result = _notify_gate({"on_link": seen.append}, "hcaptcha_image", "msg")
    assert result == {"attempted": True, "sent": True}
    assert seen == ["msg"]


def test_notify_gate_on_link_raises():
    def boom(msg):
        raise RuntimeError("telegram down")
    result = _notify_gate({"on_link": boom}, "cloudflare_interstitial", "msg")
    assert result == {"attempted": True, "sent": False}


def test_provide_guest_apply_reports_guest_action(monkeypatch):
    # _try_guest_apply is the first thing provide() calls -> no real page needed
    # when it short-circuits to True.
    monkeypatch.setattr(cp, "_try_guest_apply", lambda page: True)
    handled, action = cp.provide(page=object(), gate="password", site="example.com")
    assert (handled, action) == (True, "guest")
