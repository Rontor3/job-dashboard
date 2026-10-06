import os

import pytest

browser = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1")

# DOM order: name, country (reveals state right after it), city, notes. Every box logs when it is filled.
FORM = """
<label>Full name <input id=name></label><br>
<label>Country <select id=country><option value="">Select</option><option>India</option><option>Other</option></select></label><br>
<div id=slot></div>
<label>City <input id=city></label><br>
<label>Notes <input id=notes></label>
<script>
window.log = [];
const rec = id => e => window.log.push(id);
for (const id of ['name','city','notes']) document.getElementById(id).addEventListener('input', rec(id));
document.getElementById('country').addEventListener('change', rec('country'));
document.getElementById('country').addEventListener('change', e => {
  if (e.target.value === 'India' && !document.getElementById('state')) {
    document.getElementById('slot').innerHTML = '<label>State <input id=state></label><br>';
    document.getElementById('state').addEventListener('input', rec('state'));
  }
});
</script>"""


@browser
def test_answers_are_applied_top_down_and_a_revealed_field_takes_its_place():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form
    from career_agent.orchestrator.browser_deps import BrowserDeps
    from career_agent.orchestrator.mapper import FillDecision
    from career_agent.orchestrator.top_down import fill_top_down

    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.set_content(FORM)
        fields = snapshot_form(page)
        ref = {"notes": "#notes", "city": "#city", "country": "#country", "full name": "#name"}
        # answers handed over in the WRONG order (the order the sources found them in)
        wrong = [FillDecision(ref["notes"], "text", "Notes", "n", "fill", "t"),
                 FillDecision(ref["city"], "text", "City", "Mumbai", "fill", "t"),
                 FillDecision(ref["country"], "select", "Country", "India", "select", "t"),
                 FillDecision(ref["full name"], "text", "Full name", "Rakshit", "fill", "t")]

        def answer_new(fresh, ctx):            # what the answer ladder would say about the field that appeared
            return [FillDecision(f.ref, f.kind, f.label, "Maharashtra", "fill", "t") for f in fresh if f.label.lower().startswith("state")], []

        applied, needs = fill_top_down(page, BrowserDeps(), fields, wrong, [], {}, answer_fn=answer_new)
        assert page.evaluate("window.log") == ["name", "country", "state", "city", "notes"]
        assert [d.label.split()[0] for d in applied] == ["Full", "Country", "State", "City", "Notes"] and needs == []
        assert page.input_value("#state") == "Maharashtra" and page.input_value("#city") == "Mumbai"
        b.close()


DIV_COMBO = """
<label>Salary <input id=sal></label>
<div id="q-label">What is your notice period (in days)? (mention 0 if immediately available)</div>
<div tabindex=0 id="q1" role="combobox" aria-labelledby="q-label" aria-haspopup="dialog" aria-expanded="false" aria-controls="Popup-1"><span id=shown>Select an option</span></div>
<div id="Popup-1" style="display:none"><ul role="listbox">
  <li role="option" tabindex=0>0</li><li role="option" tabindex=0>15</li><li role="option" tabindex=0>30</li><li role="option" tabindex=0>60</li></ul></div>
<label>Location <input id=loc></label>
<script>
const box = document.getElementById('q1'), pop = document.getElementById('Popup-1');
box.addEventListener('click', () => { pop.style.display = 'block'; box.setAttribute('aria-expanded', 'true'); });
pop.querySelectorAll('[role=option]').forEach(o => o.addEventListener('click', () => {
  document.getElementById('shown').textContent = o.textContent; pop.style.display = 'none'; box.setAttribute('aria-expanded', 'false'); }));
</script>"""


@browser
def test_a_div_combobox_is_perceived_and_filled_in_page_order():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form
    from career_agent.orchestrator.browser_deps import BrowserDeps
    from career_agent.orchestrator.mapper import FillDecision
    from career_agent.orchestrator.top_down import fill_top_down

    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.set_content(DIV_COMBO)
        fields = [f for f in snapshot_form(page) if f.kind != "button"]
        assert [f.kind for f in fields] == ["text", "combobox", "text"]
        combo = fields[1]
        assert combo.label.startswith("What is your notice period") and combo.ref == "#q1"
        ds = [FillDecision(fields[2].ref, "text", "Location", "Mumbai", "fill", "t"),
              FillDecision(combo.ref, "combobox", combo.label, "30", "combobox", "t"),
              FillDecision(fields[0].ref, "text", "Salary", "25", "fill", "t")]
        applied, _ = fill_top_down(page, BrowserDeps(), fields, ds, [], {})
        assert [d.label[:6] for d in applied] == ["Salary", "What i", "Locati"]
        assert page.inner_text("#shown") == "30" and page.input_value("#loc") == "Mumbai"
        b.close()


@browser
def test_uncheck_clears_a_preticked_marketing_box_and_check_ticks_the_other():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.filler import apply_decisions
    from career_agent.orchestrator.mapper import FillDecision

    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page()
        page.set_content("<label><input type=checkbox id=m checked> Hear more about career opportunities</label>"
                         "<label><input type=checkbox id=o> Consider me for other roles</label>")
        apply_decisions(page, [FillDecision("#m", "checkbox", "m", False, "uncheck", "qbank"),
                               FillDecision("#o", "checkbox", "o", True, "check", "qbank")])
        assert not page.is_checked("#m") and page.is_checked("#o")
        apply_decisions(page, [FillDecision("#m", "checkbox", "m", False, "uncheck", "qbank")])   # idempotent
        assert not page.is_checked("#m")
        b.close()
