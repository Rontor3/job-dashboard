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


# ---- the dashboard's policy decides at the last step ------------------------------------------------------------

class _ConfirmingDeps(_Deps):
    def __init__(self, ok=True):
        self.ok = ok
    def confirmed(self, page):
        return self.ok, "page says 'application submitted'" if self.ok else "no confirmation text"


def _policy_cfg(deps, human, allow, calls):
    verdict = {"allow": allow, "reasons": [] if allow else ["first submit on x must go through you"]}
    return {"configurable": {"page": type("P", (), {"url": "https://x.example/apply"})(), "deps": deps, "human": human, "learn": None,
                             "autosubmit_policy": lambda url, decisions: verdict,
                             "on_submit": lambda values, how, url: calls.append((how, url))}}


def _review_state():
    s = _state([{"ref": "a", "kind": "text", "label": "Name", "value": "x", "action": "fill", "source": "resume"}], autonomous=False)
    s["do_submit"] = False                        # a --review run: left for the human unless the policy allows
    return s


def test_policy_allows_a_review_run_to_submit_without_asking_and_the_confirmed_submit_is_recorded():
    deps, human, calls = _ConfirmingDeps(True), _Human(ok=False), []
    out = advance_node(_review_state(), _policy_cfg(deps, human, True, calls))
    assert out == {"submitted": True, "stopped_reason": "submitted"}
    assert deps.clicked == "Submit application" and human.cards == []        # nobody was asked
    assert calls == [("auto", "https://x.example/apply")]


def test_policy_denying_leaves_the_form_for_review_untouched():
    deps, human, calls = _ConfirmingDeps(True), _Human(), []
    assert advance_node(_review_state(), _policy_cfg(deps, human, False, calls)) == {"stopped_reason": "reached_submit_dry_run"}
    assert not hasattr(deps, "clicked") and calls == []


def test_a_click_with_no_confirmation_is_not_a_submit_and_records_nothing():
    deps, human, calls = _ConfirmingDeps(False), _Human(), []
    out = advance_node(_review_state(), _policy_cfg(deps, human, True, calls))
    assert out == {"submitted": False, "stopped_reason": "submit_unconfirmed"} and calls == []


def test_board_authorization_follows_the_policy_then_a_human_yes():
    import dataclasses
    from career_agent.orchestrator.mapper import FillDecision
    page = type("P", (), {"url": "https://www.linkedin.com/jobs/view/1"})()
    d = [FillDecision("#a", "text", "Name", "x", "fill", "resume")]
    ctx = {"autosubmit_policy": lambda url, decisions: {"allow": True, "reasons": []}, "do_submit": False}
    assert _authorized(ctx, {"id": "board:linkedin"}, page, d) is True and ctx["how"] == "auto"
    ctx = {"autosubmit_policy": lambda url, decisions: {"allow": False, "reasons": ["off"]}, "do_submit": False}
    assert _authorized(ctx, {"id": "board:linkedin"}, page, d) is False and ctx["eligibility"]["reasons"] == ["off"]
    ctx = {"autosubmit_policy": lambda url, decisions: {"allow": False, "reasons": ["off"]}, "do_submit": True, "human": _Human(ok=True)}
    assert _authorized(ctx, {"id": "board:linkedin"}, page, d) is True and ctx["how"] == "tap"
