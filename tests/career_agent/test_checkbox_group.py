"""A multi-choice checkbox cluster is ONE question — fold, ask once or leave blank, tick exactly
the named options (Twilio's "How did you hear about us?" escalated nine boxes on 2026-10-19)."""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_BROWSER_TESTS"), reason="browser test")

HTML = """<html><body><form>
<fieldset><legend>How did you hear about us?</legend>
  <label><input type="checkbox" name="src" value="cw"> Careers Website</label>
  <label><input type="checkbox" name="src" value="li"> LinkedIn</label>
  <label><input type="checkbox" name="src" value="tw"> Twitter</label>
  <label><input type="checkbox" name="src" value="ot"> Other</label>
</fieldset>
<label for="nm">Name *</label><input id="nm" required></form></body></html>"""


def _read(page):
    from career_agent.browser import perception as P
    return P.to_form_model(P.collect_raw(page))


def test_a_checkbox_cluster_folds_into_one_question():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        page = p.chromium.launch().new_page()
        page.set_content(HTML)
        groups = [f for f in _read(page) if f.kind == "checkbox_group"]
        assert len(groups) == 1
        assert groups[0].label == "How did you hear about us?"
        assert groups[0].options == ["Careers Website", "LinkedIn", "Twitter", "Other"]


def test_the_folded_group_takes_the_first_boxs_place_and_singles_survive():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        page = p.chromium.launch().new_page()
        page.set_content(HTML)
        fields = _read(page)
        assert fields[0].kind == "checkbox_group"          # first box's position
        assert any(f.kind == "text" for f in fields)       # surrounding fields are intact


def test_check_multi_ticks_exactly_the_named_options():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.filler import apply_decisions
    from career_agent.orchestrator.mapper import FillDecision
    with sync_playwright() as p:
        page = p.chromium.launch().new_page()
        page.set_content(HTML)
        group = next(f for f in _read(page) if f.kind == "checkbox_group")
        d = FillDecision(group.ref, group.kind, group.label, "Careers Website, Other",
                         "check_multi", "human_prior")
        apply_decisions(page, [d])
        state = {f.get_attribute("value"): f.is_checked()
                 for f in page.locator("input[type=checkbox]").all()}
        assert state == {"cw": True, "li": False, "tw": False, "ot": True}


def test_none_of_the_boxes_are_touched_when_the_value_says_so():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.filler import apply_decisions
    from career_agent.orchestrator.mapper import FillDecision
    with sync_playwright() as p:
        page = p.chromium.launch().new_page()
        page.set_content(HTML)
        group = next(f for f in _read(page) if f.kind == "checkbox_group")
        apply_decisions(page, [FillDecision(group.ref, group.kind, group.label,
                                            "LinkedIn", "check_multi", "human")])
        state = {f.get_attribute("value"): f.is_checked()
                 for f in page.locator("input[type=checkbox]").all()}
        assert state == {"cw": False, "li": True, "tw": False, "ot": False}


def test_ladder_leaves_an_optional_group_alone_and_escalates_a_required_one_once():
    """Pure unit part: the answer ladder's rule for groups (no browser needed)."""
    from career_agent.browser.form_model import Field
    from career_agent.memory.candidate_profile import CandidateProfile
    from career_agent.orchestrator.screen_review import map_screen

    prof = CandidateProfile(contact={"full_name": "Rakshit", "email": "r@x.com"},
                            skills=["Python"])

    opt = Field(ref="#g1", kind="checkbox_group", label="How did you hear about us?",
                required=False, options=["Careers Website", "LinkedIn", "Other"], group="src")
    req = Field(ref="#g2", kind="checkbox_group", label="How did you hear about us? *",
                required=True, options=["Careers Website", "LinkedIn", "Other"], group="src2")
    dec, needs = map_screen([opt], prof)
    assert dec == [] and needs == []            # optional: blank, never nine questions

    dec, needs = map_screen([req], prof)
    assert dec == [] and [f.ref for f in needs] == ["#g2"]   # ONE question, once
