import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1",
                                reason="set RUN_BROWSER_TESTS=1 to run")


def _url(name):
    return (Path(__file__).parent / "fixtures" / name).resolve().as_uri()


def test_greenhouse_style_labels_are_captured():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.goto(_url("greenhouse_labels.html"))
        labels = [f.label for f in snapshot_form(page) if f.kind != "button"]
        b.close()
    assert any("Country" in l for l in labels)
    assert any("education" in l.lower() for l in labels)
    assert any("LinkedIn" in l for l in labels)
    assert "" not in labels          # no empty-label inputs


SF_LANG_MENU = """<html><body><form id="careerform">
<div role="list" class="userInfoMenu"><div role="listitem"><a href="javascript:void(0)" id="16:" role="combobox"
  aria-haspopup="true" title="Language" aria-label="Language">English US (English US)</a></div>
  <div role="listitem"><a href="#">Sign Out</a></div></div>
<label for="97:_input">Gender</label><input id="97:_input" role="combobox" aria-owns="98:_listSelect">
<label for="g">Grade</label><div id="g" role="combobox" aria-label="Grade" tabindex="0">No Selection</div>
</form></body></html>"""


def test_a_link_dressed_as_a_combobox_is_not_a_field():
    """SuccessFactors' site-language switcher (<a role=combobox> beside Sign Out, inside the form) was read as the
    question 'Language'; picking from it switched Wipro's site to Deutsch (live 2026-10-23)."""
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.set_content(SF_LANG_MENU)
        combos = [f.label for f in snapshot_form(page, scroll=False) if f.kind == "combobox"]
        b.close()
    assert not any("Language" in l for l in combos)
    assert any("Gender" in l for l in combos) and any("Grade" in l for l in combos)   # real ones still read
