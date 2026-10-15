"""A fill counts only when the page took it; widget internals are not fields; a file input is named by its group."""
import os

import pytest

browser = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1")

EMPLOYEE_Q = ("Are you currently an employee or contractor at Acme? "
              "(if Yes, please add your Acme email in the email section of the application page)")


def test_a_yes_no_question_that_mentions_email_is_not_the_email_field():
    from career_agent.browser.form_model import guess_purpose
    assert guess_purpose(EMPLOYEE_Q, "combobox") is None
    assert guess_purpose("Do you have a LinkedIn profile?", "text") is None
    assert guess_purpose("Email", "text") == "email"                         # a plain field keeps its purpose
    assert guess_purpose("Current Company", "text") == "employer"


def test_only_the_answer_line_of_a_chatty_reply_is_kept():
    from career_agent.orchestrator.judgment import short_answer
    assert short_answer("Yes\n\n(This assumes the job is posted in India. If it's posted elsewhere…)") == "Yes"
    assert short_answer('"No" (based on the résumé)') == "No"
    assert short_answer("Immediately") == "Immediately"
    assert short_answer("") is None
    assert short_answer("Based on the candidate profile it is not possible to say whether they have worked here") is None


# Greenhouse's react-select: a search <input role=combobox>, the choice rendered beside it, and — while a required
# dropdown is empty — a hidden <input required aria-hidden tabindex=-1> labelled only by the "Select..." placeholder.
FORM = """
<div class="select__container">
  <label id="q1-label" for="q1">%s<span aria-hidden="true">*</span></label>
  <div class="select-shell">
    <div class="select__control" id="c1"><div class="select__value-container">
      <div class="select__placeholder" id="ph">Select...</div>
      <div class="select__input-container"><input id="q1" class="select__input" role="combobox" aria-labelledby="q1-label"
           aria-required="true" aria-controls="q1-lb" aria-expanded="false" autocomplete="off"></div>
    </div></div>
    <input required aria-hidden="true" tabindex="-1" id="req" style="opacity:0;position:absolute;width:100%%">
    <div id="q1-lb" role="listbox" style="display:none">
      <div role="option" id="rs-q1-option-0">Yes</div><div role="option" id="rs-q1-option-1">No</div></div>
  </div>
</div>
<div role="group" aria-labelledby="up-cl" class="file-upload"><div id="up-cl">Cover Letter</div>
  <button type="button">Attach</button><label style="position:absolute;clip:rect(0 0 0 0)" for="cover_letter">Attach</label>
  <input id="cover_letter" type="file" style="position:absolute;opacity:0;width:1px;height:1px"></div>
<script>
const inp = document.getElementById('q1'), lb = document.getElementById('q1-lb');
inp.addEventListener('focus', () => { lb.style.display = 'block'; });
inp.addEventListener('mousedown', () => { lb.style.display = 'block'; });
inp.addEventListener('keydown', e => { if (e.key === 'Escape') { lb.style.display = 'none'; } });
for (const o of lb.querySelectorAll('[role=option]')) o.addEventListener('click', () => {
  const ph = document.getElementById('ph'); if (ph) ph.outerHTML = '<div class="select__single-value">' + o.textContent + '</div>';
  const r = document.getElementById('req'); if (r) r.remove();
  lb.style.display = 'none'; inp.value = '';
});
</script>""" % EMPLOYEE_Q


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        p = b.new_page(); p.set_content(FORM)
        yield p
        b.close()


@browser
def test_widget_internals_are_not_fields_and_a_file_is_named_by_its_group(page):
    from career_agent.browser.perception import snapshot_form
    fields = {f.label.split("?")[0].strip(): f for f in snapshot_form(page, scroll=False)}
    assert not any(lbl.startswith("Select") for lbl in fields)                  # the hidden required stand-in is gone
    assert "Cover Letter" in fields and fields["Cover Letter"].kind == "file"
    assert fields["Cover Letter"].purpose != "resume_upload"
    assert any(lbl.startswith("Are you currently an employee") for lbl in fields)


@browser
def test_a_dropdown_answer_that_matches_no_option_is_not_counted_filled(page):
    from career_agent.browser.filler import field_value
    from career_agent.browser.perception import snapshot_form
    from career_agent.orchestrator.browser_deps import BrowserDeps
    from career_agent.orchestrator.mapper import FillDecision
    from career_agent.orchestrator.top_down import fill_top_down
    fields = snapshot_form(page, scroll=False)
    q = next(f for f in fields if f.label.startswith("Are you currently"))
    bad = FillDecision(q.ref, "combobox", q.label, "someone@example.com", "combobox", "resume")
    applied, needs = fill_top_down(page, BrowserDeps(), fields, [bad], [], {}, answer_fn=lambda f, c: ([], []))
    assert applied == [] and [n.label for n in needs] == [q.label]               # goes to the human, real label
    assert field_value(page, "#q1") == ""

    good = FillDecision(q.ref, "combobox", q.label, "No", "combobox", "judgment")
    applied, needs = fill_top_down(page, BrowserDeps(), fields, [good], [], {}, answer_fn=lambda f, c: ([], []))
    assert applied == [good] and needs == []
    assert field_value(page, "#q1") == "No"                                       # the choice, not the empty search box
