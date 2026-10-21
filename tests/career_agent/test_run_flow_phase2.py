from career_agent.browser.form_model import Field
from career_agent import run as runmod


class FakePage:
    def __init__(self): self.submitted = False
    def click_submit(self): self.submitted = True


class FakeNotifier:
    def __init__(self): self.started = []
    def start(self, url, gate, deadline_s):
        import threading
        self.started.append((url, gate)); return threading.Event()
    def close(self, cleared=None): pass


class HumanStub:
    def __init__(self, approve, solve):
        self._a = approve
        self._s = solve
    def approve(self, card): return self._a
    def remote_solve(self, page, gate, notifier):
        if notifier: notifier.start("http://mac.ts.net:8765/s/abc", gate, 300)
        return self._s


def _form():
    return [Field("#n", "text", "Full name", True, [], None, "full_name")]


def _meta():
    return {"company": "Acme", "role": "Eng", "portal": "acme.com"}


def _patch(monkeypatch, gates):
    # gates is a list of classify_gate return values across successive calls
    seq = iter(gates)
    monkeypatch.setattr(runmod, "snapshot_form", lambda p: _form())
    monkeypatch.setattr(runmod, "classify_gate", lambda p: next(seq))
    monkeypatch.setattr(runmod, "apply_decisions", lambda p, d: None)


def test_interactive_gate_triggers_remote_solve_then_submits(monkeypatch):
    _patch(monkeypatch, ["hcaptcha_checkbox", "none"])  # after solve -> none
    page = FakePage()
    human = HumanStub(approve=True, solve=True)
    notifier = FakeNotifier()
    out = runmod.run_once(page, {"full_name": "T"}, None, _meta(), human,
                          do_submit=True, notifier=notifier)
    assert out["remote_solve_attempted"] is True
    assert out["gate_after_solve"] == "none"
    assert out["submitted"] is True and page.submitted is True
    # the link + gate were forwarded to the notifier for delivery
    assert notifier.started == [("http://mac.ts.net:8765/s/abc", "hcaptcha_checkbox")]


def test_failed_remote_solve_blocks_submit(monkeypatch):
    _patch(monkeypatch, ["hcaptcha_checkbox"])  # never re-classified (solve fails)
    page = FakePage()
    human = HumanStub(approve=True, solve=False)
    out = runmod.run_once(page, {"full_name": "T"}, None, _meta(), human, do_submit=True)
    assert out["remote_solve_attempted"] is True
    assert out["submitted"] is False and page.submitted is False


def test_clear_gate_skips_remote_solve(monkeypatch):
    _patch(monkeypatch, ["none"])
    page = FakePage()
    human = HumanStub(approve=True, solve=True)
    out = runmod.run_once(page, {"full_name": "T"}, None, _meta(), human, do_submit=True)
    assert out["remote_solve_attempted"] is False
    assert out["submitted"] is True
