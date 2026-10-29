"""A comma list in a picker: a multi-select gets every item; a single-choice field keeps its first pick."""
import os
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")

PAGE_T = """
<div class="field" data-automation-id="formField-skills">
  <input id="s" data-automation-id="searchBox" role="combobox" aria-controls="lb" autocomplete="off">
  <div role="listbox" id="lb" style="display:none"></div>
</div>
<script>
const CATALOG = __CATALOG__; const MULTI = __MULTI__;
const input = document.getElementById("s"), lb = document.getElementById("lb");
const field = document.querySelector('[data-automation-id="formField-skills"]');
function render() {
  const q = input.value.trim().toLowerCase();
  lb.innerHTML = "";
  CATALOG.filter(t => !q || t.toLowerCase().includes(q)).forEach(t => {
    const o = document.createElement("div"); o.setAttribute("role", "option"); o.textContent = t;
    o.addEventListener("click", () => {
      const s = document.createElement("span"); s.setAttribute("data-automation-id", "selectedItem"); s.textContent = t;
      if (!MULTI) field.querySelectorAll('[data-automation-id="selectedItem"]').forEach(x => x.remove());
      field.insertBefore(s, input); input.value = ""; render(); lb.style.display = "none";
    });
    lb.appendChild(o);
  });
  lb.style.display = "block";
}
input.addEventListener("click", render);
input.addEventListener("input", render);
</script>
"""


def _run(catalog, multi, value):
    import json
    from playwright.sync_api import sync_playwright
    from career_agent.browser.filler import _add_list_parts, _pick_combobox

    html = PAGE_T.replace("__CATALOG__", json.dumps(catalog)).replace("__MULTI__", "true" if multi else "false")
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.set_content(html)
        d = SimpleNamespace(value=value, label="Skills", alternatives=(), action="combobox")
        _pick_combobox(page, page, "#s", d, None)        # what apply_decisions does: the pick, then the list's other items
        _add_list_parts(page, page, "#s", d, None)
        picked = page.locator('[data-automation-id="selectedItem"]').all_text_contents()
        b.close()
    return picked


def test_comma_list_picks_each_part():
    picked = _run(["Python", "SQL", "NumPy"], True, "Python, MCP protocol, SQL, NumPy")
    assert {"Python", "SQL", "NumPy"} <= set(picked), picked


def test_single_choice_keeps_its_first_pick():
    picked = _run(["Mumbai", "Santacruz (E)"], False, "Santacruz (E), Mumbai")
    assert len(picked) == 1 and picked[0] in ("Mumbai", "Santacruz (E)"), picked   # one answer, never a churned blank
