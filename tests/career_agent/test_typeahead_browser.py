"""A type-ahead with no ARIA (Lever 'Current location'): read as a combobox, and the picker picks from its rows."""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")

PAGE = """<label><div>Current location ✱</div><div class=application-field>
<input class=location-input id=loc type=text name=location required>
<input id=sel type=hidden name=selectedLocation value="">
<div class=dropdown-container style="display:none"><div class="dropdown-results"></div></div></div></label>
<label for=org>Current company</label><input id=org name=org>
<script>
const box = document.getElementById('loc'), res = document.querySelector('.dropdown-results');
box.addEventListener('input', () => {
  const q = box.value.trim().toLowerCase(); res.innerHTML = '';
  res.parentElement.style.display = q ? 'flex' : 'none';
  for (const c of ['Mumbai, Maharashtra, IND', 'Mumbra, Maharashtra, IND'])
    if (q && c.toLowerCase().startsWith(q)) {
      const d = document.createElement('div'); d.className = 'dropdown-location'; d.textContent = c;
      d.onclick = () => { box.value = c; document.getElementById('sel').value = c; res.parentElement.style.display = 'none'; };
      res.appendChild(d);
    }
});
box.addEventListener('blur', () => setTimeout(() => { if (!document.getElementById('sel').value) box.value = ''; }, 300));
</script>"""


def test_a_plain_typeahead_is_a_combobox_and_keeps_the_picked_row():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form
    from career_agent.browser.filler import apply_decisions
    from career_agent.orchestrator.mapper import FillDecision
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.set_content(PAGE)
        kinds = {f.ref: f.kind for f in snapshot_form(page, scroll=False)}
        assert kinds["#loc"] == "combobox" and kinds["#org"] == "text"
        apply_decisions(page, [FillDecision("#loc", "combobox", "Current location", "Mumbai, India", "combobox", "qbank")])
        page.wait_for_timeout(600)
        got = page.evaluate("[document.getElementById('loc').value, document.getElementById('sel').value]")
        b.close()
    assert got == ["Mumbai, Maharashtra, IND"] * 2
