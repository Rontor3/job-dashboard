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


def test_an_off_screen_honeypot_box_is_not_a_field():
    from playwright.sync_api import sync_playwright
    from career_agent.browser import perception as P
    html = """<form><label for=n>Name</label><input id=n>
      <div><style>.hp { position: absolute !important; left: -9999vw !important; }</style>
      <label class=hp for=h>Phone</label><input class=hp id=h type=tel style="position:absolute;left:-9999vw"></div></form>"""
    with sync_playwright() as p:
        page = p.chromium.launch().new_page()
        page.set_content(html)
        labels = [f.label for f in P.to_form_model(P.collect_raw(page))]
        assert labels == ["Name"]


def test_an_off_screen_radio_under_a_drawn_button_is_still_a_field():
    from playwright.sync_api import sync_playwright
    from career_agent.browser import perception as P
    html = """<form><fieldset><legend>Current? *</legend>
      <input type=radio name=c id=c1 style="position:absolute;left:-9990px"><label for=c1>Yes</label>
      <input type=radio name=c id=c2 style="position:absolute;left:-9990px"><label for=c2>No</label></fieldset></form>"""
    with sync_playwright() as p:
        page = p.chromium.launch().new_page()
        page.set_content(html)
        groups = [f for f in P.to_form_model(P.collect_raw(page)) if f.kind == "radio_group"]
        assert len(groups) == 1 and groups[0].options == ["Yes", "No"]
