"""RemoteSolveNotifier: formats the remote-solve Telegram card (gate + link +
TTL countdown + Abort button), watches for an Abort tap, and reports the
outcome. Fake client + injected `spawn` keep it deterministic (no real thread
except the one dedicated wiring test)."""
from career_agent.integrations.telegram.remote_solve import RemoteSolveNotifier


class FakeClient:
    def __init__(self, poll_returns=None):
        self.sent = []
        self._poll = list(poll_returns or [])

    def send_message(self, text, buttons=None):
        self.sent.append((text, buttons))
        return 1

    def poll_callback(self, timeout_s, valid):
        return self._poll.pop(0) if self._poll else None


def test_start_sends_gate_link_and_countdown_with_abort_button():
    c = FakeClient()
    n = RemoteSolveNotifier(c, spawn=lambda target: None)  # don't run the watcher
    ev = n.start("http://mac.ts.net:8765/s/abc", "hcaptcha_checkbox", 300)
    text, buttons = c.sent[0]
    assert "hcaptcha" in text.lower()                      # gate type
    assert "http://mac.ts.net:8765/s/abc" in text          # tap-to-solve link
    assert "5 min" in text                                 # 300s -> ~5 min countdown
    assert buttons == [[("🛑 Abort", "abort")]]            # Abort inline button
    assert ev.is_set() is False


def test_abort_tap_sets_event_and_close_reports_aborted():
    c = FakeClient(poll_returns=["abort"])
    n = RemoteSolveNotifier(c, spawn=lambda target: target(), poll_interval_s=0)
    ev = n.start("http://h/s/t", "recaptcha_v2_image", 120)
    assert ev.is_set() is True
    n.close(cleared=False)
    outcome = " ".join(t for (t, _b) in c.sent[1:]).lower()
    assert "abort" in outcome


def test_close_cleared_sends_continue_message():
    c = FakeClient()
    n = RemoteSolveNotifier(c, spawn=lambda target: None)
    n.start("http://h/s/t", "hcaptcha_checkbox", 300)
    n.close(cleared=True)
    outcome = " ".join(t for (t, _b) in c.sent[1:]).lower()
    assert "cleared" in outcome or "continu" in outcome


def test_close_timeout_sends_still_blocked_message():
    c = FakeClient()
    n = RemoteSolveNotifier(c, spawn=lambda target: None)
    n.start("http://h/s/t", "hcaptcha_checkbox", 300)
    n.close(cleared=False)  # event never set -> timed out
    outcome = " ".join(t for (t, _b) in c.sent[1:]).lower()
    assert "resend" in outcome or "still blocked" in outcome


def test_close_without_start_is_a_safe_noop():
    c = FakeClient()
    n = RemoteSolveNotifier(c, spawn=lambda target: None)
    n.close(cleared=False)  # start() never called
    assert c.sent == []


def test_watcher_thread_sets_event_on_abort():
    # the real (default) thread path: a background poll sees Abort and fires the event
    c = FakeClient(poll_returns=["abort"])
    n = RemoteSolveNotifier(c, poll_interval_s=0)
    ev = n.start("http://h/s/t", "hcaptcha_checkbox", 300)
    assert ev.wait(1.0) is True
    n.close(cleared=False)
