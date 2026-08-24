from career_agent.browser.form_model import Field
from career_agent import run as runmod


class FakePage:
    def __init__(self): self.submitted = False
    def click_submit(self): self.submitted = True


class HumanStub:
    def __init__(self, approve, solve):
        self._a = approve
        self._s = solve
    def approve(self, card): return self._a
    def remote_solve(self, page, gate, on_link):
        if on_link: on_link("http://mac.ts.net:8765/s/abc")
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
    seen = {}
    out = runmod.run_once(page, {"full_name": "T"}, None, _meta(), human,
                          do_submit=True, on_link=lambda u: seen.setdefault("u", u))
    assert out["remote_solve_attempted"] is True
    assert out["gate_after_solve"] == "none"
    assert out["submitted"] is True and page.submitted is True
    assert seen["u"].endswith("/s/abc")


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
