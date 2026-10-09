from career_agent.integrations.human_loop import HumanLoop


class YesApprover:
    def request(self, card): return True


class NoApprover:
    def __init__(self): self.cards = []
    def request(self, card): self.cards.append(card); return False


def test_approve_delegates():
    no = NoApprover()
    assert HumanLoop(no).approve("card") is False
    assert no.cards == ["card"]


def test_remote_solve_without_factory_returns_false():
    # no live-view configured -> caller must degrade to stop-and-report
    hl = HumanLoop(YesApprover(), remote_solve_factory=None)
    result = hl.remote_solve(page=object(), gate="hcaptcha_checkbox", on_link=lambda u: None)
    assert not result
    assert result.sent is False


def test_remote_solve_with_factory_reports_link_and_outcome():
    seen = {}
    class FakeSession:
        def __init__(self, page): pass
        def start(self): return "http://mac.ts.net:8765/s/abc"
        def wait_until_cleared(self, timeout_s): return True
        def close(self): seen["closed"] = True
    hl = HumanLoop(YesApprover(), remote_solve_factory=lambda page: FakeSession(page))
    result = hl.remote_solve(page=object(), gate="hcaptcha_checkbox",
                             on_link=lambda u: seen.setdefault("url", u))
    assert result
    assert result.sent is True
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
    result = hl.remote_solve(page=object(), gate="hcaptcha_checkbox", on_link=lambda u: None)
    assert not result
    assert result.sent is False   # start() raised before the link could be sent
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
    result = hl.remote_solve(page=object(), gate="hcaptcha_checkbox", on_link=lambda u: None)
    assert not result
    assert result.sent is False
