"""A SuccessFactors-shaped application page (Wipro, live 2026-10-23), offline:
- UI5 date pickers each hide an <input id="inner"> in a shadow root: every date box needs its own address;
- section titles are inline <h2>s wrapping a block button (0x0): fields must still get 'Education' etc.;
- a cascading State turns usable once Country is picked: the page signature must change so the form is re-read;
- the résumé slot has no file input until its '+' icon opens a dialog."""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")

PAGE = """<html><body><form>
<div><h2 class="sectionTitle"><button style="display:block;width:600px;height:40px">Professional Experience</button></h2>
  <label>Start Date</label><x-date></x-date></div>
<div><h2 class="sectionTitle"><button style="display:block;width:600px;height:40px">Education</button></h2>
  <label>Start Date</label><x-date></x-date>
  <label for="st">State</label><input id="st" disabled></div>
<div class="attachmentField"><label>Resume/CV</label>
  <span id="ariaAct" style="display:none">Upload a Resume Opens a dialog</span>
  <span id="plus" aria-labelledby="ariaAct" onclick="openDlg()" style="display:inline-block;width:20px;height:20px">+</span>
  <span id="got"></span></div>
</form>
<script>
customElements.define('x-date', class extends HTMLElement { constructor() { super();
  this.attachShadow({mode: 'open'}).innerHTML = '<input id="inner" type="text" placeholder="MM/DD/YYYY" aria-label="Start Date">'; } });
function openDlg() { const d = document.createElement('div'); d.setAttribute('role', 'dialog');
  d.innerHTML = 'Upload from Device <input type="file">'; document.body.appendChild(d);
  d.querySelector('input').onchange = e => { document.getElementById('got').textContent = e.target.files[0].name; d.remove(); }; }
</script></body></html>"""


def test_successfactors_dates_sections_cascade_and_upload(tmp_path):
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import FIELD_SIG_JS, snapshot_form
    from career_agent.browser.filler import upload_resume_via_control
    pdf = tmp_path / "Rakshit_Singh_Resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    with sync_playwright() as pw:
        b = pw.chromium.launch(); pg = b.new_page(); pg.set_content(PAGE)
        dates = [f for f in snapshot_form(pg, scroll=False) if "Start Date" in (f.label or "")]
        assert len(dates) == 2 and dates[0].ref != dates[1].ref               # not both '#inner'
        assert [f.section for f in dates] == ["Professional Experience", "Education"]
        pg.fill(dates[1].ref, "07/01/2019")                                    # the second box, not the first
        assert pg.evaluate("[...document.querySelectorAll('x-date')].map(x => x.shadowRoot.querySelector('input').value)") \
            == ["", "07/01/2019"]
        before = pg.evaluate(FIELD_SIG_JS)
        pg.evaluate("document.getElementById('st').disabled = false")         # Country picked: State opens
        assert pg.evaluate(FIELD_SIG_JS) != before
        assert upload_resume_via_control(pg, str(pdf)) is not None
        pg.wait_for_timeout(300)
        assert pg.text_content("#got") == "Rakshit_Singh_Resume.pdf"
        b.close()
