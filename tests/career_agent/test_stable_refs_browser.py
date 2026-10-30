"""Zoho (live 2026-10-31): the résumé parse added rows between two reads; every read restamped from f0, so the first
read's ref for LinkedIn pointed at Institute #1 and the URL was typed there."""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")

PAGE = """<div id="edu"></div>
<div><label>LinkedIn</label><div><input type="text" name="rec-form_1"></div></div>"""


def test_a_ref_from_an_earlier_read_still_names_the_same_box():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.set_content(PAGE)
        first = {f.label: f.ref for f in snapshot_form(page, scroll=False)}
        page.evaluate("""() => document.getElementById('edu').innerHTML =
            '<div><label>Institute / School</label><input type=text name=rec-form_2></div>'.repeat(3)""")
        snapshot_form(page, scroll=False)                      # a re-read while filling
        page.fill(first["LinkedIn"], "https://www.linkedin.com/in/x")
        linked = page.input_value('[name="rec-form_1"]')
        b.close()
    assert linked == "https://www.linkedin.com/in/x"
