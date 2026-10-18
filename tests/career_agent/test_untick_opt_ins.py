"""Optional opt-ins are unticked before moving on; required boxes and consent to apply are never touched."""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")

PAGE = """<html><body>
<label><input type=checkbox id=a checked> I agree to receive updates about new job opportunities.</label>
<label><input type=checkbox id=b checked> Get the latest Cummins' Jobs, News and Articles delivered to your inbox</label>
<label><input type=checkbox id=c checked required> I agree with the Privacy Notice</label>
<label><input type=checkbox id=d checked> I certify the information above is true</label>
</body></html>"""


def test_optional_opt_ins_go_required_and_attestations_stay():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.page_prep import untick_opt_ins
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(); pg.set_content(PAGE)
        assert untick_opt_ins(pg) == 2                     # both Cummins opt-ins (live 2026-10-18)
        state = pg.evaluate("() => ['a','b','c','d'].map(i => document.getElementById(i).checked)")
        b.close()
    assert state == [False, False, True, True]
