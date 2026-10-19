"""A styled combobox (select2 / div[role=combobox]) is seen on EVERY read of the page, not only the first."""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_BROWSER_TESTS"), reason="browser test")

HTML = """<form><label id="cc-label">Country Phone Code *</label>
<select id="cc" aria-hidden="true" style="position:absolute;width:1px;height:1px;overflow:hidden"></select>
<span role="combobox" aria-labelledby="cc-label" aria-required="true" tabindex="0"
      style="display:inline-block;width:200px;height:30px">Select an option</span>
<label for="ph">Phone Number *</label><input id="ph" type="tel"></form>"""


def test_a_styled_combobox_survives_a_second_read():
    from playwright.sync_api import sync_playwright
    from career_agent.browser import perception as P
    with sync_playwright() as p:
        page = p.chromium.launch().new_page()
        page.set_content(HTML)
        reads = [[f.kind for f in P.to_form_model(P.collect_raw(page))] for _ in range(2)]
        assert reads[0].count("combobox") == 1 and reads[1].count("combobox") == 1
