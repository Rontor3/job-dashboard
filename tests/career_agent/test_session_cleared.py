from career_agent.integrations.live_view.session import RemoteSolveSession


class FakePage:
    """`signals` drives classify_gate (via _gather_signals -> page.evaluate)."""
    def __init__(self, url, signals=None):
        self.url = url
        self._signals = signals if signals is not None else {"hcaptcha_iframe": True}

    def evaluate(self, js):
        return self._signals


def _sess(page, is_cleared, start_url):
    s = RemoteSolveSession(page, "127.0.0.1", 8765, ttl_s=300,
                           allow_public=False, is_cleared=is_cleared)
    s._start_url = start_url
    return s


def test_cleared_on_in_place_token():
    s = _sess(FakePage("http://a/step1"), lambda p: True, "http://a/step1")
    assert s._cleared() is True


def test_not_cleared_when_token_absent_gate_present_same_url():
    # gate widget still on the page (hcaptcha_iframe present) -> keep waiting
    page = FakePage("http://a/step1", signals={"hcaptcha_iframe": True})
    s = _sess(page, lambda p: False, "http://a/step1")
    assert s._cleared() is False


def test_cleared_when_navigated_past_gate():
    # multi-page: solving advanced to the next screen -> URL changed
    s = _sess(FakePage("http://a/step2"), lambda p: False, "http://a/step1")
    assert s._cleared() is True


def test_cleared_when_spa_gate_disappears_debounced():
    # SPA advance: same URL, but the captcha widget is gone (no signals).
    page = FakePage("http://a/step1", signals={})   # classify_gate -> "none"
    s = _sess(page, lambda p: False, "http://a/step1")
    assert s._cleared() is False   # 1st gone poll (debounce)
    assert s._cleared() is True    # 2nd consecutive gone poll -> cleared


def test_gone_debounce_resets_if_gate_reappears():
    page = FakePage("http://a/step1", signals={})   # gone
    s = _sess(page, lambda p: False, "http://a/step1")
    assert s._cleared() is False                    # gone_polls = 1
    page._signals = {"hcaptcha_iframe": True}        # gate back (mid-solve blip)
    assert s._cleared() is False                    # resets
    page._signals = {}                              # gone again
    assert s._cleared() is False                    # gone_polls = 1 again
    assert s._cleared() is True                     # gone_polls = 2


def test_cleared_when_context_destroyed_mid_navigation():
    def boom(p):
        raise RuntimeError("Execution context was destroyed, most likely because of a navigation")
    s = _sess(FakePage("http://a/step1"), boom, "http://a/step1")
    assert s._cleared() is True
