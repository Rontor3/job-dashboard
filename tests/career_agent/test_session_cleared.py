from career_agent.integrations.live_view.session import RemoteSolveSession


class FakePage:
    """`flag` is what the in-page solve observer would report via evaluate."""
    def __init__(self, url, flag=False, evaluate_raises=False):
        self.url = url
        self._flag = flag
        self._raises = evaluate_raises

    def evaluate(self, js):
        if self._raises:
            raise RuntimeError("Execution context was destroyed, most likely because of a navigation")
        return self._flag


def _sess(page, is_cleared, start_url):
    s = RemoteSolveSession(page, "127.0.0.1", 8765, ttl_s=300,
                           allow_public=False, is_cleared=is_cleared)
    s._start_url = start_url
    return s


def test_cleared_when_token_flag_latched():
    # the in-page observer caught the response token
    s = _sess(FakePage("http://a/step1", flag=True), lambda p: False, "http://a/step1")
    assert s._cleared() is True


def test_cleared_via_is_cleared_fallback():
    s = _sess(FakePage("http://a/step1", flag=False), lambda p: True, "http://a/step1")
    assert s._cleared() is True


def test_not_cleared_when_no_token_same_url():
    # THE FALSE-POSITIVE GUARD: dismissing a popup (no token, no navigation)
    # must NOT be treated as a solve.
    s = _sess(FakePage("http://a/step1", flag=False), lambda p: False, "http://a/step1")
    assert s._cleared() is False


def test_cleared_when_navigated_multi_page():
    s = _sess(FakePage("http://a/step2", flag=False), lambda p: False, "http://a/step1")
    assert s._cleared() is True


def test_cleared_when_context_destroyed_mid_navigation():
    s = _sess(FakePage("http://a/step1", evaluate_raises=True), lambda p: False, "http://a/step1")
    assert s._cleared() is True
