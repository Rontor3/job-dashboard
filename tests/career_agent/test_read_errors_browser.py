"""aria-describedby is the site's help/status text unless the field is invalid or the node is error-shaped.

Workday points describedby at screen-reader status ('0 items selected', 'current value is 7/2023'); read as errors
it buried the real 'Contains illegal characters' message (Opella/Trinity, live 2026-10-26)."""
import os

import pytest

from career_agent.browser.validation import read_errors

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")

PAGE = """<html><body>
<input id="skills" aria-describedby="s1"><span id="s1">0 items selected</span>
<input id="start" aria-describedby="s2" value="07/2023"><span id="s2">current value is 7/2023</span>
<input id="hint" aria-describedby="s3"><span id="s3">Format: MM/YYYY</span>
<input id="role" aria-invalid="true" aria-describedby="e1"><span id="e1">Contains illegal characters</span>
<input id="city" aria-describedby="e2"><span id="e2" class="error-msg">City is required</span>
<input id="phone" required>
</body></html>"""


def test_status_text_is_not_an_error_but_real_errors_are():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.set_content(PAGE)
        got = {e["ref"]: e["message"] for e in read_errors(page)}
        b.close()
    assert "#skills" not in got and "#start" not in got and "#hint" not in got
    assert got["#role"] == "Contains illegal characters"
    assert got["#city"] == "City is required"
    assert "#phone" in got                              # native :invalid, no words of its own needed
