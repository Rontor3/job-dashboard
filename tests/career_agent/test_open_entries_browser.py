"""Workday My Experience (Walmart, live 2026-10-30): Work Experience / Education are a heading and a bare 'Add'."""
import os
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")

PAGE = """
<div role="group"><h3>Work Experience</h3><div class="rows"></div><button>Add</button></div>
<div role="group"><h3>Education</h3><div class="rows"></div><button>Add</button></div>
<div role="group"><h3>Languages</h3><div class="rows"></div><button>Add</button></div>
<script>
let n = 300;
document.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
  const g = b.closest('[role=group]'), key = g.querySelector('h3').innerText.startsWith('Work') ? 'workExperience' : 'education';
  const i = n++, k = g.querySelectorAll('.rows h4').length + 1;   // Workday: an entry has its own heading and a 'From*' legend
  g.querySelector('.rows').insertAdjacentHTML('beforeend',
    `<h4>${g.querySelector('h3').innerText} ${k}</h4><input id="${key}-${i}--jobTitle"><input id="${key}-${i}--companyName">
     <fieldset><legend>From*</legend><input id="${key}-${i}--startDate"></fieldset>`);
  b.innerText = 'Add Another';
}));
</script>
"""


def test_each_section_gets_one_entry_per_profile_item():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.entries import open_entries
    profile = SimpleNamespace(experiences=["Tata AIG", "OYO"], education=["IIT (BHU)"])
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.set_content(PAGE)
        assert open_entries(page, profile) == 3
        assert open_entries(page, profile) == 0                      # a second pass adds nothing
        work = page.locator('[id^="workExperience-"][id$="--jobTitle"]').count()
        edu = page.locator('[id^="education-"][id$="--jobTitle"]').count()
        langs = page.locator('[role=group]').nth(2).locator('input').count()
        b.close()
    assert (work, edu, langs) == (2, 1, 0)
