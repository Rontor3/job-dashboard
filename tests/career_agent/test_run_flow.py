from career_agent.browser.form_model import Field
from career_agent.integrations.human_loop import HumanLoop
from career_agent.run import run_once


class FakePage:
    def __init__(self, form): self._form = form; self.submitted = False
    def _snapshot(self): return self._form
    def click_submit(self): self.submitted = True


class YesApprover:
    def request(self, card): return True


class NoApprover:
    def request(self, card): return False


def _form():
    return [Field("#n", "text", "Full name", True, [], None, "full_name"),
            Field("#c", "checkbox", "I certify true", False, [], None, "attestation")]


def _meta():
    return {"company": "Acme", "role": "Engineer", "portal": "acme.com"}


def test_dry_run_never_submits(monkeypatch):
    page = FakePage(_form())
    monkeypatch.setattr("career_agent.run.snapshot_form", lambda p: p._snapshot())
    monkeypatch.setattr("career_agent.run.classify_gate", lambda p: "none")
    monkeypatch.setattr("career_agent.run.apply_decisions", lambda p, d: None)
    out = run_once(page, {"full_name": "T"}, None, _meta(), HumanLoop(YesApprover()),
                    do_submit=False)
    assert out["submitted"] is False
    assert out["remote_solve_attempted"] is False
    assert "Acme" in out["card"]


def test_submit_requires_approval_and_clear_gate(monkeypatch):
    page = FakePage(_form())
    monkeypatch.setattr("career_agent.run.snapshot_form", lambda p: p._snapshot())
    monkeypatch.setattr("career_agent.run.classify_gate", lambda p: "none")
    monkeypatch.setattr("career_agent.run.apply_decisions", lambda p, d: None)
    out = run_once(page, {"full_name": "T"}, None, _meta(), HumanLoop(YesApprover()),
                    do_submit=True)
    assert out["approved"] is True and out["submitted"] is True and page.submitted is True
    assert out["remote_solve_attempted"] is False


def test_escalated_gate_blocks_submit(monkeypatch):
    page = FakePage(_form())
    monkeypatch.setattr("career_agent.run.snapshot_form", lambda p: p._snapshot())
    monkeypatch.setattr("career_agent.run.classify_gate", lambda p: "cloudflare_interstitial")
    monkeypatch.setattr("career_agent.run.apply_decisions", lambda p, d: None)
    out = run_once(page, {"full_name": "T"}, None, _meta(), HumanLoop(YesApprover()),
                    do_submit=True)
    assert out["submitted"] is False
    assert out["remote_solve_attempted"] is False
    assert "cloudflare_interstitial" in out["card"]
