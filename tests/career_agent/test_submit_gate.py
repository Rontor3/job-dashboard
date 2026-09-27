"""Autonomous submit must still surface for human review when the fill
contains a qbank_likely (below-confident) best-guess answer."""
from career_agent.browser.form_model import Field
from career_agent.orchestrator.graph import advance_node
from career_agent.boards.run import _authorized


def _submit_form():
    return [_f2d(Field("#s", "button", "Submit application", False))]


def _f2d(f):
    import dataclasses
    return dataclasses.asdict(f)


class _Deps:
    def gate(self, page):
        return "none"

    def click(self, page, label):
        self.clicked = label


class _Human:
    def __init__(self, ok=True):
        self.ok = ok
        self.cards = []

    def approve(self, card):
        self.cards.append(card)
        return self.ok


def _state(decisions, autonomous=True):
    return {
        "stopped_reason": None, "form": _submit_form(), "do_submit": True,
        "autonomous": autonomous, "decisions": decisions,
    }


def _config(deps, human):
    return {"configurable": {"page": object(), "deps": deps, "human": human, "learn": None}}


def test_autonomous_submits_when_no_likely_decisions():
    deps, human = _Deps(), _Human(ok=True)
    out = advance_node(_state([{"ref": "a", "kind": "text", "label": "Name",
                                 "value": "x", "action": "fill", "source": "rules"}]),
                        _config(deps, human))
    assert out["stopped_reason"] == "submitted"
    assert human.cards == []          # no per-app tap needed


def test_autonomous_still_asks_when_a_likely_decision_present():
    deps, human = _Deps(), _Human(ok=True)
    out = advance_node(_state([{"ref": "a", "kind": "text", "label": "Name",
                                 "value": "x", "action": "fill", "source": "qbank_likely"}]),
                        _config(deps, human))
    assert human.cards, "autonomous must not skip review when a likely fill exists"
    assert "best-guess" in human.cards[0].lower()
    assert out["stopped_reason"] == "submitted"


def test_autonomous_declined_review_stops():
    deps, human = _Deps(), _Human(ok=False)
    out = advance_node(_state([{"ref": "a", "kind": "text", "label": "Name",
                                 "value": "x", "action": "fill", "source": "qbank_likely"}]),
                        _config(deps, human))
    assert out["stopped_reason"] == "submit_declined"


def test_boards_authorized_counts_qbank_likely_as_needing_review():
    ctx = {"do_submit": True, "autonomous": True, "human": _Human(ok=True)}
    page = type("P", (), {"url": "http://x"})()
    decisions = [type("D", (), {"label": "Name", "value": "x", "source": "qbank_likely"})()]
    assert _authorized(ctx, {"id": "b"}, page, decisions) is True
    assert ctx["human"].cards, "must go through human.approve when a likely decision exists"
