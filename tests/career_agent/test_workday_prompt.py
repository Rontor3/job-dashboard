"""Workday prompt dropdowns: a search box that opens a popup, a hierarchical "How did you hear" list, and a
phone-code search. Live 2026-10-18 (Salesforce wd12 30026, Hitachi wd1 29991): each stayed empty and the form would
not advance. The choice must be a selectedItem pill, reached through the popup, with a leaf picked from sub-lists."""
import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_TESTS") != "1",
    reason="set RUN_BROWSER_TESTS=1 to run",
)


def _fixture_url():
    return (Path(__file__).parent / "fixtures" / "workday_prompt.html").resolve().as_uri()


def _run(decisions):
    from playwright.sync_api import sync_playwright
    from career_agent.browser.filler import apply_decisions, field_value
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(_fixture_url())
        apply_decisions(page, decisions)
        out = {d.ref: field_value(page, d.ref) for d in decisions}
        browser.close()
    return out


def _decision(ref, label, value):
    from career_agent.orchestrator.mapper import FillDecision
    return FillDecision(ref, "combobox", label, value, "combobox", "profile")


def test_hierarchical_prompt_picks_category_then_leaf():
    # "Job Board" is a category: it opens LinkedIn / Indeed / Other. No leaf fits the answer, so "Other" is picked.
    got = _run([_decision("#hear", "How Did You Hear About Us?", "Job Board")])
    assert got["#hear"] == "Other"


def test_search_prompt_types_the_value_and_takes_the_matching_option():
    # Nothing is listed until something is typed; "+91" matches "India (+91)".
    got = _run([_decision("#phone", "Country Phone Code", "+91")])
    assert got["#phone"] == "India (+91)"


def test_workday_search_box_is_perceived_as_combobox():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(_fixture_url())
        form = snapshot_form(page)
        browser.close()
    by_ref = {f.ref: f for f in form}
    assert by_ref["#hear"].kind == "combobox"
    assert by_ref["#phone"].kind == "combobox"
