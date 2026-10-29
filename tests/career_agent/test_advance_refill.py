"""advance_node acts on the site's field errors even when the screen fingerprint moved.

Workday adds boxes when it shows an error (Opella 55→57 fields, 2026-10-24); the old unchanged-only check printed the
red text, ignored it, and re-filled the whole step in a loop."""
import dataclasses

from career_agent.browser import page_prep, validation
from career_agent.browser.form_model import Field
from career_agent.orchestrator import graph

NEXT = Field(ref="#next", kind="button", label="Next", required=False)
ROLE = Field(ref="#role", kind="text", label="Role", required=True)


class _Page:
    url = "https://x.example/apply"


class _Deps:
    def __init__(self, form):
        self.form = form

    def click(self, page, label):
        pass

    def snapshot(self, page, scroll=True):
        return self.form

    def url(self, page):
        return page.url


def _run(monkeypatch, before, after, errors):
    calls = []
    monkeypatch.setattr(validation, "read_errors", lambda page, limit=12: errors)
    monkeypatch.setattr(validation, "progress_signature", lambda page: "")
    monkeypatch.setattr(page_prep, "untick_opt_ins", lambda page: None)
    monkeypatch.setattr(page_prep, "classify_entry", lambda page: "form")
    monkeypatch.setattr(graph, "_validation_refill",
                        lambda page, deps, fail, c, state: calls.append([f.ref for f in fail]) or {"decisions": []})
    from career_agent.orchestrator.advance import screen_signature
    state = {"form": [dataclasses.asdict(f) for f in before], "decisions": [{"ref": "#role"}], "do_submit": False,
             "autonomous": False, "steps": 1, "form_sig": screen_signature(_Page.url, before, "")}
    cfg = {"configurable": {"page": _Page(), "deps": _Deps(after), "human": None}}
    return graph.advance_node(state, cfg), calls


def test_errors_on_a_shifted_screen_are_refilled(monkeypatch):
    extra = Field(ref="#extra", kind="text", label="Extra", required=False)
    out, calls = _run(monkeypatch, [ROLE, NEXT], [ROLE, extra, NEXT],
                      [{"ref": "#role", "message": "Contains illegal characters"}])
    assert calls == [["#role"]]
    assert out["refilled"]


def test_no_errors_on_a_new_screen_moves_on(monkeypatch):
    other = Field(ref="#city", kind="text", label="City", required=True)
    out, calls = _run(monkeypatch, [ROLE, NEXT], [other, NEXT], [])
    assert calls == [] and "stopped_reason" not in out


def test_walk_refills_flagged_fields_then_stops_needs_answers_if_still_red(monkeypatch):
    """walk() (the graph's fallback) reads the same red boxes: the flagged field goes to the human, then one more
    Next; still red and unmoved → needs_answers, not a bare 'stuck'."""
    from career_agent.memory.candidate_profile import CandidateProfile
    from career_agent.orchestrator.step_engine import walk
    monkeypatch.setattr(validation, "read_errors", lambda page, limit=12: [{"ref": "#role", "message": "Required"}])
    asked, clicks = [], []

    class Deps(_Deps):
        def gate(self, page): return "none"
        def fill(self, page, decisions): pass
        def click(self, page, label): clicks.append(label)

    class Human:
        def collect(self, fields): asked.append([f.ref for f in fields]); return {}

    out = walk(_Page(), CandidateProfile(), Human(), Deps([ROLE, NEXT]), do_submit=False)
    assert ["#role"] in asked and len(clicks) == 2
    assert out["stopped_reason"] == "needs_answers"


def _signup(monkeypatch, refill_result, after_kind):
    from career_agent.browser import credential_provider as cp
    from types import SimpleNamespace
    radios = Field(ref="group:visible", kind="radio_group", label="Make My Profile Visible to", required=True)
    monkeypatch.setattr(graph, "perceive_node", lambda state, config: {})
    monkeypatch.setattr(cp, "provide", lambda *a, **k: (False, "register"))
    monkeypatch.setattr(page_prep, "clear_auth_wall", lambda page, credential_provider: credential_provider(page, "g", "s"))
    monkeypatch.setattr(page_prep, "is_application_form", lambda page: False)
    monkeypatch.setattr(page_prep, "classify_entry", lambda page: after_kind)
    monkeypatch.setattr(cp, "wall_reason", lambda page: "auth_wall")
    monkeypatch.setattr(page_prep, "reach_application_form", lambda page: (page, None))
    clicks = []
    monkeypatch.setattr(cp, "_click_non_social_submit", lambda page: clicks.append(1) or True)
    monkeypatch.setattr(cp, "_observe_until_change", lambda page, label: "unknown")
    monkeypatch.setattr(validation, "read_errors", lambda page, limit=12: [{"ref": "group:visible", "message": ""}])
    monkeypatch.setattr(graph, "_validation_refill", lambda page, deps, fail, c, state: refill_result(fail))
    page = SimpleNamespace(url="https://x/register")
    cfg = {"configurable": {"page": page, "deps": _Deps([radios]), "profile": None}}
    return graph.cred_provide_node({"url": page.url}, cfg), clicks


def test_signup_red_radios_with_no_answer_park_as_needs_answers(monkeypatch):
    out, clicks = _signup(monkeypatch, lambda fail: {"pending_human": [dataclasses.asdict(f) for f in fail]}, "password")
    assert out["stopped_reason"] == "needs_answers" and clicks == []
    assert out["pending_human"][0]["label"] == "Make My Profile Visible to"


def test_signup_red_radios_answered_then_submitted_again(monkeypatch):
    out, clicks = _signup(monkeypatch, lambda fail: {"decisions": []}, "form")
    assert clicks == [1] and "stopped_reason" not in out and out["cred_provided"]
