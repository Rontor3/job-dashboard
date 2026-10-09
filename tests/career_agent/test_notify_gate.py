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


class _El:
    def __init__(self, text, clicks):
        self.text, self.clicks = text, clicks
    def is_visible(self): return True
    def text_content(self): return self.text
    def get_attribute(self, name): return None
    def click(self): self.clicks.append(self.text)


class _GuestPage:
    def __init__(self):
        self.clicks = []
    def query_selector_all(self, sel):
        return [_El("Sign in", self.clicks), _El("Apply as guest", self.clicks)]
    def wait_for_timeout(self, ms): pass


def test_a_guest_path_is_taken_without_creating_an_account(monkeypatch, tmp_path):
    store = tmp_path / "credentials.json"
    monkeypatch.setattr(cp, "_STORE", store)
    page = _GuestPage()
    assert cp.provide(page=page, gate="password", site="example.com") == (True, "guest")
    assert page.clicks == ["Apply as guest"]
    assert not store.exists()
