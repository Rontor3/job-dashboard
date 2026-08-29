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


def test_remote_solve_degrades_when_start_raises():
    # a live-view that fails to stand up (start raises) must NOT crash the run
    # -> return False (stop-and-report) and still close the session.
    seen = {}
    class BrokenSession:
        def __init__(self, page): pass
        def start(self): raise RuntimeError("port bind failed")
        def wait_until_cleared(self, timeout_s): return True  # never reached
        def close(self): seen["closed"] = True
    hl = HumanLoop(YesApprover(), remote_solve_factory=lambda page: BrokenSession(page))
    assert hl.remote_solve(page=object(), gate="hcaptcha_checkbox",
                           on_link=lambda u: None) is False
    assert seen["closed"] is True


def test_remote_solve_passes_gate_to_gate_aware_factory():
    # a factory taking (page, gate) gets the real gate (so it can watch the
    # right captcha token on a dual-captcha page).
    seen = {}
    class FakeSession:
        def __init__(self, page, gate): seen["gate"] = gate
        def start(self): return "http://x/s"
        def wait_until_cleared(self, timeout_s): return True
        def close(self): pass
    hl = HumanLoop(YesApprover(), remote_solve_factory=lambda page, gate: FakeSession(page, gate))
    hl.remote_solve(page=object(), gate="hcaptcha_image", on_link=lambda u: None)
    assert seen["gate"] == "hcaptcha_image"


def test_remote_solve_degrades_when_factory_raises():
    # factory itself raising (no session created) must also degrade cleanly.
    def boom(page): raise RuntimeError("cannot detect viewport")
    hl = HumanLoop(YesApprover(), remote_solve_factory=boom)
    assert hl.remote_solve(page=object(), gate="hcaptcha_checkbox",
                           on_link=lambda u: None) is False
