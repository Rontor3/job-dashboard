import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_TESTS") != "1",
    reason="set RUN_BROWSER_TESTS=1 to run",
)


def _fixture_url():
    return (Path(__file__).parent / "fixtures" / "workday_select_button.html").resolve().as_uri()


def test_aria_listbox_button_classified_as_combobox_with_clean_label():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(_fixture_url())
        form = snapshot_form(page)
        browser.close()

    by_ref = {f.ref: f for f in form}
    state = by_ref["#address--countryRegion"]
    assert state.kind == "combobox"
    assert state.label == "State"
    assert state.required is True


def test_hidden_file_input_behind_a_visible_label_is_seen():
    """Live Pelicon form 2026-10-12: the résumé input is display:none behind a styled label; it was never attached."""
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form

    html = ("<form><label>Full Name <input name=n></label>"
            "<label for=cv class=btn>Click to select mandatory resume file (.pdf) *</label>"
            "<input type=file id=cv name=attachment style='display:none'>"
            "<input type=file name=ghost style='display:none'></form>")       # no label shown: still skipped
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(html)
        form = snapshot_form(page)
        browser.close()
    files = [f for f in form if f.kind == "file"]
    assert len(files) == 1 and "resume" in files[0].label.lower()


def test_uxi_widget_input_classified_as_combobox():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(_fixture_url())
        form = snapshot_form(page)
        browser.close()

    by_ref = {f.ref: f for f in form}
    src = by_ref["#source--source"]
    assert src.kind == "combobox"


def test_listbox_button_with_empty_aria_name_falls_back_to_fieldset_text():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(_fixture_url())
        form = snapshot_form(page)
        browser.close()

    by_ref = {f.ref: f for f in form}
    q = by_ref["#primaryQuestionnaire--legalName"]
    assert q.kind == "combobox"
    assert "Legal Name" in q.label
    assert q.label != "Select One"
