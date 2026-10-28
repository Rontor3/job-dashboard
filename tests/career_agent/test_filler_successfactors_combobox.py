"""A SuccessFactors picklist (Wipro, live 2026-10-23): input[role=combobox] tied to its list by aria-owns, an id with a
colon ("322:_listSelect"), rows drawn ~0.8 s after the click, and a 'required' flag re-checked only on blur. Every one
of those left the box at 'No Selection'; and 'Male' clicked 'Female' (substring match)."""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")

SF_PICKLIST = """<html><body>
<label for="97:_input">* Gender</label>
<input id="97:_input" role="combobox" aria-owns="98:_listSelect" aria-invalid="true" placeholder="No Selection"
  onclick="setTimeout(() => { document.getElementById('98:_listSelect').innerHTML =
     ['No Selection','Female','Male'].map(t => `<li role=option onclick=&quot;pick('${t}')&quot;>${t}</li>`).join(''); }, 800)"
  onblur="this.setAttribute('aria-invalid', this.value && this.value !== 'No Selection' ? 'false' : 'true')">
<ul id="98:_listSelect" role="listbox"></ul>
<script>function pick(t){ const i = document.getElementById('97:_input'); i.value = t;
  document.getElementById('98:_listSelect').innerHTML = ''; }</script>
</body></html>"""


def test_successfactors_picklist_takes_the_exact_option_and_clears_its_flag():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.filler import _pick_combobox
    from career_agent.orchestrator.mapper import FillDecision
    ref = "#\\39 7\\:_input"
    with sync_playwright() as pw:
        b = pw.chromium.launch(); pg = b.new_page(); pg.set_content(SF_PICKLIST)
        _pick_combobox(pg, pg, ref, FillDecision(ref, "combobox", "Gender", "Male", "combobox", "test"), None)
        pg.wait_for_timeout(300)
        assert pg.input_value(ref) == "Male"                   # not 'Female', not left at No Selection
        assert pg.get_attribute(ref, "aria-invalid") == "false"
        b.close()
