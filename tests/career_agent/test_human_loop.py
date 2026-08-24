from career_agent.integrations.human_loop import HumanLoop


class YesApprover:
    def request(self, card): return True


def test_approve_delegates():
    assert HumanLoop(YesApprover()).approve("card") is True


def test_remote_solve_without_factory_returns_false():
    # no live-view configured -> caller must degrade to stop-and-report
    hl = HumanLoop(YesApprover(), remote_solve_factory=None)
    assert hl.remote_solve(page=object(), gate="hcaptcha_checkbox", on_link=lambda u: None) is False


def test_remote_solve_with_factory_reports_link_and_outcome():
    seen = {}
    class FakeSession:
        def __init__(self, page): pass
        def start(self): return "http://mac.ts.net:8765/s/abc"
        def wait_until_cleared(self, timeout_s): return True
        def close(self): seen["closed"] = True
    hl = HumanLoop(YesApprover(), remote_solve_factory=lambda page: FakeSession(page))
    ok = hl.remote_solve(page=object(), gate="hcaptcha_checkbox",
                         on_link=lambda u: seen.setdefault("url", u))
    assert ok is True
    assert seen["url"].endswith("/s/abc")
    assert seen["closed"] is True
