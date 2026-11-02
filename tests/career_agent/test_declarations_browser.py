"""A bare 'Acceptance: Yes/No' asks about the statement above it; a declaration's one assent option is picked
(Innovecture on Indeed 2026-11-02: both were asked of the human and the page parked)."""
import os

import pytest

from career_agent.browser.form_model import Field
from career_agent.orchestrator.screen_review import _assent, map_screen

PAGE = """<div><div>I certify that my answers to all questions are true and correct without any omissions.</div>
<fieldset><legend>Acceptance *</legend><div><div><label><input type=radio name=acc value=Yes required>Yes</label>
<label><input type=radio name=acc value=No>No</label></div></div></fieldset></div>
<fieldset><legend>Favourite colour</legend><label><input type=radio name=col value=Red>Red</label>
<label><input type=radio name=col value=Blue>Blue</label></fieldset>"""


def test_the_assent_option_is_picked_and_never_a_no():
    assert _assent(["I have read and agree to this statement"]) == "I have read and agree to this statement"
    assert _assent(["I agree", "I do not agree"]) == "I agree"
    assert _assent(["Red", "Blue"]) is None


def test_a_single_assent_declaration_is_answered():
    from types import SimpleNamespace as N
    f = Field("#p", "radio_group", "By checking this box, you acknowledge and consent to terms of the privacy policy *",
              True, options=["I have read and agree to this statement"], purpose="attestation")
    d, needs = map_screen([f], N(experiences=[], education=[], skills=[], contact={}))
    assert [x.value for x in d] == ["I have read and agree to this statement"] and needs == []


@pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")
def test_a_bare_label_reads_the_statement_above_it():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.set_content(PAGE)
        got = {f.label.strip(" *"): (f.purpose, f.description[:20]) for f in snapshot_form(page, scroll=False) if f.kind == "radio_group"}
        b.close()
    assert got["Acceptance"] == ("attestation", "I certify that my an")
    assert got["Favourite colour"][0] is None
