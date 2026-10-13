"""Form patterns that recur across ATSes, each handled by its structural signal (not by site):
a unit control sharing an amount's row, number-only boxes, a star-only label, a web component's shadow input,
a site-prefilled field, a calendar with short month names in a <select>, and a cookie banner's "settings" button."""
import os
from datetime import date

import pytest

browser = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1")


def test_an_amount_is_written_in_the_unit_its_row_shows():
    from career_agent.orchestrator.answering import shape_value
    assert shape_value("35 LPA", "Expected Salary *", "text", "INR") == "3500000"        # INR beside the box -> rupees
    assert shape_value("35 LPA", "Expected Salary *", "text", "") == "35 LPA"            # nothing says: unambiguous LPA
    assert shape_value("35", "Expected CTC (in LPA)", "text", "INR") == "35"             # the label's own unit wins
    assert shape_value("30 days", "Available To Join (in days)", "number") == "30"       # number box: the number alone
    assert shape_value("2-4 years", "Years of Python", "number") == "2"
    assert shape_value("Mumbai", "City", "text", "") == "Mumbai"


FORM = """
<div class="row"><div class="col-3"><input id="cur" value="INR" readonly></div>
  <div class="col"><label for="exp">Expected Salary</label><input id="exp" type="text"></div></div>
<div class="row"><select id="cc"><option value="">-</option><option value="USD">USD</option><option value="INR" selected>INR</option></select>
  <input id="now" type="text" aria-label="Current Salary"></div>
<div><label for="avail">Available To Join (in days)</label><input id="avail" type="number"></div>
<div><label for="yrs">Experience</label><input id="yrs" type="text" value="3"></div>
<div class="consent"><input type="checkbox" id="pol"><label for="pol">*</label>
  <p>Please be informed that your application will trigger processing of your personal data.</p></div>
<my-input id="city" label="City"></my-input>
<my-check id="consent"><span slot="label">Please be informed that we process your data.</span></my-check>
<script>
customElements.define('my-check', class extends HTMLElement {
  constructor() { super(); this.attachShadow({mode: 'open'}).innerHTML = '<input type="checkbox" required><label>*<slot name="label"></slot></label>'; } });
customElements.define('my-input', class extends HTMLElement {
  constructor() { super(); this.attachShadow({mode: 'open'}).innerHTML = '<input type="text">'; } });
</script>"""


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        p = b.new_page()
        yield p
        b.close()


@browser
def test_unit_star_label_shadow_value_and_prefilled(page):
    from career_agent.browser.filler import field_value, has_value
    from career_agent.browser.perception import snapshot_form
    page.set_content(FORM)
    by = {f.ref: f for f in snapshot_form(page, scroll=False)}
    assert by["#exp"].unit == "INR" and by["#now"].unit == "INR"
    assert by["#avail"].input_type == "number" and by["#avail"].unit == ""
    assert by["#pol"].label.startswith("Please be informed")                    # not "*"
    shadow_box = [f for f in by.values() if f.kind == "checkbox" and f.ref != "#pol"]
    assert shadow_box and shadow_box[0].label.startswith("Please be informed that we process")   # slotted host text
    page.evaluate("document.querySelector('#city').shadowRoot.querySelector('input').value = 'Mumbai'")
    assert field_value(page, "#city") == "Mumbai"                                # read through the shadow root
    page.evaluate("document.querySelector('#city').shadowRoot.querySelector('input').value = ''")
    assert field_value(page, "#city") == ""                                      # empty = did not take, not "unknown"
    assert has_value(page, by["#yrs"]) and not has_value(page, by["#avail"])    # the site's "3" is an answer


# A calendar whose month/year are <select>s with SHORT month names and a grid of plain day numbers.
CAL = """
<input id="dob" readonly>
<div id="cal" style="display:none;border:1px solid">
  <select id="m">%s</select><select id="y">%s</select>
  <table id="grid"></table></div>
<script>
const inp = document.getElementById('dob'), cal = document.getElementById('cal');
const m = document.getElementById('m'), y = document.getElementById('y'), grid = document.getElementById('grid');
function draw() {
  const n = new Date(+y.value, +m.value + 1, 0).getDate(); let h = '<tr>';
  for (let d = 1; d <= n; d++) { h += '<td><a href="#">' + d + '</a></td>'; if (d %% 7 === 0) h += '</tr><tr>'; }
  grid.innerHTML = h + '</tr>';
  grid.querySelectorAll('td').forEach(td => td.addEventListener('click', e => { e.preventDefault();
    inp.value = String(td.textContent).padStart(2, '0') + '/' + String(+m.value + 1).padStart(2, '0') + '/' + y.value;
    cal.style.display = 'none'; }));
}
m.addEventListener('change', draw); y.addEventListener('change', draw);
inp.addEventListener('click', () => { cal.style.display = 'block'; draw(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') cal.style.display = 'none'; });
</script>""" % ("".join(f'<option value="{i}"{" selected" if i == 9 else ""}>{n}</option>'
                        for i, n in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())),
                "".join(f'<option value="{yr}"{" selected" if yr == 2026 else ""}>{yr}</option>' for yr in range(1980, 2027)))


@browser
def test_a_calendar_with_short_month_names_is_driven_and_a_failed_one_is_closed(page):
    from career_agent.browser.date_widgets import pick_calendar
    page.set_content(CAL)
    assert pick_calendar(page, page, "#dob", date(2001, 3, 17)) is True
    assert page.input_value("#dob") == "17/03/2001"
    page.evaluate("document.getElementById('dob').value = ''")
    assert pick_calendar(page, page, "#dob", date(1900, 1, 1)) is False       # no such year on offer
    assert not page.is_visible("#cal")                                           # not left covering the form


BANNER = """<div role="dialog" aria-label="cookies">We use cookies.
  <button onclick="document.getElementById('pc').style.display='block'">Cookies Settings</button>
  <button onclick="this.parentElement.remove()">Got it</button></div>
<div id="pc" style="display:none">Privacy Preference Center</div>"""


@browser
def test_a_cookie_banner_is_closed_without_opening_its_settings(page):
    from career_agent.browser.page_prep import dismiss_consent
    page.set_content(BANNER)
    assert dismiss_consent(page) is True
    assert not page.is_visible("#pc")                                            # "OK" no longer matches "Cookies"
    assert page.locator("[role=dialog]").count() == 0
