"""SECTION RULES (browser/perception.py): headings name sections, legends never; 'Work Experience 2' is entry 2."""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")

PAGE = """<h2>My Experience</h2>
<h3>Work Experience 1</h3><label for=t1>Job Title</label><input id=t1>
<fieldset><legend>From*</legend><input id=m1 aria-label=Month><input id=y1 aria-label=Year></fieldset>
<h3>Work Experience 2</h3><label for=t2>Job Title</label><input id=t2>
<fieldset><legend>From*</legend><input id=m2 aria-label=Month><input id=y2 aria-label=Year></fieldset>
<h3>Social Network URLs</h3><label for=li>LinkedIn</label><input id=li>"""


def test_headings_name_sections_and_numbers_name_entries():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.set_content(PAGE)
        got = {f.ref: (f.section, f.row) for f in snapshot_form(page, scroll=False)}
        b.close()
    assert got["#t1"] == got["#m1"] == got["#y1"] == ("Work Experience", 0)      # 'From*' is part of the entry
    assert got["#t2"] == got["#y2"] == ("Work Experience", 1)
    assert got["#li"][0] == "Social Network URLs"
