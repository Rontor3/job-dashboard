"""A choose-how-to-apply page is entered by its manual option; a hidden Apply opens nothing; nothing filled is no_form_found."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from career_agent.browser.form_model import Field
from career_agent.orchestrator.advance import entry_apply_label, submit_seen
from career_agent.orchestrator.graph import advance_node, _f2d
from career_agent.orchestrator.step_engine import walk
from career_agent.memory.candidate_profile import CandidateProfile

FIXTURE = (Path(__file__).parent / "fixtures" / "choose_apply_manual_option.html").resolve().as_uri()
browser = pytest.mark.skipif(not os.environ.get("RUN_BROWSER_TESTS"), reason="browser")


def _b(label):
    return Field("#" + label, "button", label, False, [], None, None)


def test_a_hidden_apply_is_not_the_entry_and_is_not_a_submit():
    form = [_b("Default Apply")]
    assert entry_apply_label(form, [], {"from device"}) is None                 # not visible on the page
    assert entry_apply_label(form, [], {"default apply"}) == "Default Apply"
    assert entry_apply_label(form, [], None) == "Default Apply"                 # no visibility info: unchanged rule
    assert submit_seen(form) is False                                           # 'Apply' alone is an entry, not a submit
    assert submit_seen([_b("Submit application")]) is True


def test_zero_filled_with_only_a_hidden_apply_is_no_form_found_not_a_dry_run_success(monkeypatch):
    from career_agent.browser import page_prep
    monkeypatch.setattr(page_prep, "visible_clickable_names", lambda page: {"from device"})   # the Apply is not shown
    state = {"steps": 1, "decisions": [], "form": [_f2d(_b("Default Apply"))], "stopped_reason": None,
             "max_steps": 15, "do_submit": False, "form_sig": None}
    cfg = {"configurable": {"page": SimpleNamespace(url="https://x/jd"), "deps": SimpleNamespace(), "human": None}}
    assert advance_node(state, cfg)["stopped_reason"] == "no_form_found"


class _Deps:
    def __init__(self, screens): self._screens, self._i = screens, 0
    def snapshot(self, page, scroll=True): return self._screens[min(self._i, len(self._screens) - 1)]
    def gate(self, page): return "none"
    def fill(self, page, decisions): pass
    def click(self, page, label): self._i += 1
    def url(self, page): return f"http://x/step{self._i}"


class _Human:
    def approve(self, card): return True
    def remote_solve(self, page, gate, on_link): return True
    def collect(self, fields): return {}


def test_walk_with_nothing_filled_and_only_an_apply_reports_no_form_found():
    screen = [Field("#a", "Default Apply", "Default Apply", False, [], None, None)]
    screen[0] = Field("#a", "button", "Default Apply", False, [], None, None)
    out = walk(object(), CandidateProfile(), _Human(), _Deps([screen]), do_submit=False)
    assert out["stopped_reason"] == "no_form_found"


def test_jd_page_with_only_a_visible_apply_now_link_clicks_it_before_giving_up(monkeypatch):
    """insyncanalytics: the snapshot shows only a captcha widget; the visible 'Apply Now' link is the way in."""
    from career_agent.browser import page_prep
    from career_agent.orchestrator import graph
    monkeypatch.setattr(page_prep, "find_apply_affordance", lambda page, **kw: {"name": "Apply Now", "role": "link", "ref": None, "frame": 0})
    monkeypatch.setattr(page_prep, "classify_entry", lambda page, status=None: "unknown")
    deps = _Deps([[Field("#b", "button", "Begin", False, [], None, None)]])
    clicked = []
    deps.click = lambda page, label: clicked.append(label)
    state = {"steps": 1, "decisions": [], "form": [_f2d(Field("#b", "button", "Begin", False, [], None, None))],
             "stopped_reason": None, "max_steps": 15, "do_submit": False, "form_sig": None, "url": "https://x/jd"}
    page = SimpleNamespace(url="https://x/jd", frames=[], wait_for_timeout=lambda ms: None)
    cfg = {"configurable": {"page": page, "deps": deps, "human": _Human()}}
    out = graph.advance_node(state, cfg)
    assert clicked == ["Apply Now"]
    assert out.get("stopped_reason") != "no_advance_control"


@browser
def test_choose_how_to_apply_page_is_entered_by_its_manual_option():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.page_prep import reach_application_form, visible_clickable_names
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.goto(FIXTURE)
        assert "default apply" not in (visible_clickable_names(page) or set())   # visibility:hidden is not a control
        active, status = reach_application_form(page)
        assert status == "form"
        assert active.locator("input[name=email]").is_visible()
        b.close()
