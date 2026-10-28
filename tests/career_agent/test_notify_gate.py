from career_agent.orchestrator import graph as g
from career_agent.orchestrator.graph import _notify_gate
import career_agent.browser.credential_provider as cp


def test_notify_gate_no_channel_at_all():
    # Telegram not wired at all (e.g. --no-telegram / CLI collector): nothing to
    # notify through, attempted stays False — honest, not skipped silently.
    result = _notify_gate({}, "otp_sms", "msg")
    assert result == {"attempted": False, "sent": False, "queued": False}


def test_notify_gate_on_link_succeeds():
    seen = []
    result = _notify_gate({"on_link": seen.append}, "hcaptcha_image", "msg")
    assert result == {"attempted": True, "sent": True, "queued": False}
    assert seen == ["msg"]


def test_notify_gate_retries_a_failing_transport(monkeypatch):
    # A transport that only LOOKS down must not skip the notice (live class A
    # 2026-10-20: two hcaptcha runs logged notified: False over Telegram blips).
    # Telegram sends are idempotent text: retry, and deliver on attempt 2.
    monkeypatch.setattr(g.time, "sleep", lambda s: None)
    calls = []
    def flaky(msg):
        calls.append(msg)
        if len(calls) == 1:
            raise RuntimeError("telegram down")
    result = _notify_gate({"on_link": flaky}, "hcaptcha_image", "msg")
    assert result == {"attempted": True, "sent": True, "queued": False}
    assert calls == ["msg", "msg"]


def test_notify_gate_records_queued_when_the_transport_stays_down(monkeypatch):
    monkeypatch.setattr(g.time, "sleep", lambda s: None)
    def boom(msg):
        raise RuntimeError("telegram down")
    result = _notify_gate({"on_link": boom}, "cloudflare_interstitial", "msg")
    assert result == {"attempted": True, "sent": False, "queued": True}


def test_park_mode_notifies_through_the_collectors_own_channel():
    # --park sets on_link=None, but the collector still carries a live Telegram
    # notify (EscalationCollector / ParkCollector): the notice must go out now.
    seen = []
    c = {"collector": type("P", (), {"notify": seen.append})()}
    assert _notify_gate(c, "hcaptcha_image", "msg") == {"attempted": True, "sent": True, "queued": False}
    assert seen == ["msg"]


def test_a_telegram_collector_client_serves_as_the_channel():
    seen = []
    c = {"collector": type("T", (), {"client": type("C", (), {"send_message": lambda self, text: seen.append(text)})()})()}
    assert _notify_gate(c, "otp_email", "msg")["sent"] is True
    assert seen == ["msg"]


def test_provide_guest_apply_reports_guest_action(monkeypatch):
    # _try_guest_apply is the first thing provide() calls -> no real page needed
    # when it short-circuits to True.
    monkeypatch.setattr(cp, "_try_guest_apply", lambda page: True)
    handled, action = cp.provide(page=object(), gate="password", site="example.com")
    assert (handled, action) == (True, "guest")


def test_park_result_summary_carries_the_gate_notice():
    from career_agent.integrations.park import result_summary
    out = {"url": "https://x.example/jobs/1", "board": "naukri", "submitted": False,
           "stopped_reason": "gate:hcaptcha_checkbox", "decisions": [], "pending_human": [],
           "gate_notice": {"gate": "hcaptcha_checkbox", "attempted": True, "sent": False, "queued": True}}
    s = result_summary(out)
    assert s["gate_notice"]["queued"] is True          # the offline run recorded it pinged-or-not
    assert result_summary({"stopped_reason": "dry_run"})["gate_notice"] is None
