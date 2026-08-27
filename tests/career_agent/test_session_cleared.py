from career_agent.integrations.live_view.session import RemoteSolveSession


class FakePage:
    """`flag` is what the in-page token observer reports via evaluate
    (window.__cca_cleared / localStorage)."""
    def __init__(self, flag=False, evaluate_raises=False):
        self._flag = flag
        self._raises = evaluate_raises

    def evaluate(self, js):
        if self._raises:
            raise RuntimeError("Execution context was destroyed, most likely because of a navigation")
        return self._flag


def _sess(page, is_cleared):
    return RemoteSolveSession(page, "127.0.0.1", 8765, ttl_s=300,
                              allow_public=False, is_cleared=is_cleared)


def test_cleared_when_token_latched():
    assert _sess(FakePage(flag=True), lambda p: False)._cleared() is True


def test_cleared_via_is_cleared_fallback():
    assert _sess(FakePage(flag=False), lambda p: True)._cleared() is True


def test_not_cleared_without_token():
    # THE FALSE-POSITIVE GUARD: no captcha token means NOT solved, even though a
    # consent-popup dismissal may have navigated/reloaded the page.
    assert _sess(FakePage(flag=False), lambda p: False)._cleared() is False


def test_evaluate_error_is_not_a_solve():
    # a transient / mid-navigation evaluate error must NOT be treated as cleared
    assert _sess(FakePage(evaluate_raises=True), lambda p: False)._cleared() is False
