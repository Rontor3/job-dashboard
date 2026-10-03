import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_TESTS") != "1",
    reason="set RUN_BROWSER_TESTS=1 to run",
)


def _fixture_url():
    return (Path(__file__).parent / "fixtures" / "sample_form.html").resolve().as_uri()


def test_fill_then_readback_matches():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.filler import apply_decisions, read_back
    from career_agent.orchestrator.mapper import FillDecision

    decisions = [
        FillDecision("#name", "text", "Full name", "Jane Q", "fill", "profile"),
        FillDecision("#email", "email", "Email", "jane@example.com", "fill", "profile"),
    ]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(_fixture_url())
        apply_decisions(page, decisions)
        values = read_back(page, decisions)
        browser.close()

    assert values["#name"] == "Jane Q"
    assert values["#email"] == "jane@example.com"


_YES_NO_PAGE = """<form>""" + "".join(
    f"""<fieldset><legend>{q} *</legend>
      <label><input type="radio" name="q_{i}" value="opt{i}a" {'checked' if pre == 'Yes' else ''}><span>Yes</span></label>
      <label><input type="radio" name="q_{i}" value="opt{i}b" {'checked' if pre == 'No' else ''}><span>No</span></label>
    </fieldset>"""
    for i, (q, pre) in enumerate([("Are you willing to relocate for this role?", "No"),
                                  ("Are you willing to travel in this role if required?", ""),
                                  ("Are you legally eligible to work in the country/region in which this job is located?", "No"),
                                  ("Have you previously worked with Siemens?", "")])) + "</form>"


def test_each_yes_no_question_gets_its_own_answer_over_the_sites_prefill():
    # live Indeed (Siemens) 2026-10-12: every pick clicked the page's FIRST Yes/No, so relocate ended 'No'
    # and the board's pre-filled 'No' on eligibility stayed
    from playwright.sync_api import sync_playwright
    from career_agent.browser.filler import apply_decisions
    from career_agent.browser.perception import snapshot_form
    from career_agent.orchestrator.mapper import FillDecision

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(_YES_NO_PAGE)
        groups = [f for f in snapshot_form(page) if f.kind == "radio_group"]
        assert len(groups) == 4
        want = ["Yes", "Yes", "Yes", "No"]
        apply_decisions(page, [FillDecision(g.ref, g.kind, g.label, w, "check_group", "qbank")
                               for g, w in zip(groups, want)])
        got = page.evaluate("""() => [0,1,2,3].map(i => {
            const c = document.querySelector(`input[name=q_${i}]:checked`);
            return c ? c.parentElement.innerText.trim() : null; })""")
        browser.close()
    assert got == want

def test_check_group_ticks_the_option_in_its_own_group_when_several_share_yes_no():
    # Live LinkedIn 2026-10-03: three Yes/No questions; "Yes" for the 2nd/3rd landed on the 1st.
    from playwright.sync_api import sync_playwright
    from career_agent.browser.filler import apply_decisions
    from career_agent.orchestrator.mapper import FillDecision
    html = ("<fieldset><legend>Onsite?</legend><label><input type=radio name=q1 value=y>Yes</label>"
            "<label><input type=radio name=q1 value=n>No</label></fieldset>"
            "<fieldset><legend>Salary?</legend><label><input type=radio name=q2 value=y>Yes</label>"
            "<label><input type=radio name=q2 value=n>No</label></fieldset>"
            "<div role='radiogroup' data-cref-group='g9'><div role='radio' tabindex=0 onclick=\"this.setAttribute('aria-checked','true')\">Yes</div>"
            "<div role='radio' tabindex=0 onclick=\"this.setAttribute('aria-checked','true')\">No</div></div>")
    with sync_playwright() as pw:
        b = pw.chromium.launch(); pg = b.new_page(); pg.set_content(html)
        apply_decisions(pg, [FillDecision("group:q2", "radio_group", "Salary?", "Yes", "check_group", "human"),
                             FillDecision("group:q1", "radio_group", "Onsite?", "No", "check_group", "human"),
                             FillDecision("group:g9", "radio_group", "Custom?", "No", "check_group", "human")])
        state = pg.evaluate("()=>({q1:document.querySelector('input[name=q1]:checked')?.value, q2:document.querySelector('input[name=q2]:checked')?.value,"
                            " g9:[...document.querySelectorAll('[data-cref-group=g9] [role=radio]')].map(e=>e.getAttribute('aria-checked'))})")
        b.close()
    assert state == {"q1": "n", "q2": "y", "g9": [None, "true"]}
