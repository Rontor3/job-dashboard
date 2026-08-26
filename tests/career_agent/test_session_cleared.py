from career_agent.integrations.live_view.session import RemoteSolveSession


class FakePage:
    def __init__(self, url):
        self.url = url


def _sess(page, is_cleared, start_url):
    s = RemoteSolveSession(page, "127.0.0.1", 8765, ttl_s=300,
                           allow_public=False, is_cleared=is_cleared)
    s._start_url = start_url
    return s


def test_cleared_on_in_place_token():
    s = _sess(FakePage("http://a/step1"), lambda p: True, "http://a/step1")
    assert s._cleared() is True


def test_not_cleared_when_no_token_and_same_url():
    s = _sess(FakePage("http://a/step1"), lambda p: False, "http://a/step1")
    assert s._cleared() is False


def test_cleared_when_navigated_past_gate():
    # solving advanced the flow to the next screen -> URL changed
    s = _sess(FakePage("http://a/step2"), lambda p: False, "http://a/step1")
    assert s._cleared() is True


def test_cleared_when_context_destroyed_mid_navigation():
    def boom(p):
        raise RuntimeError("Execution context was destroyed, most likely because of a navigation")
    s = _sess(FakePage("http://a/step1"), boom, "http://a/step1")
    assert s._cleared() is True
