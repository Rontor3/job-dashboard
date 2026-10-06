import os
import pytest
from career_agent.browser.confirmation import confirmation_from_signals as c


def test_a_confirmation_needs_the_words_and_the_form_gone():
    assert c({"text": "Your application was submitted to Weekday", "fields": 0})[0]
    assert c({"text": "Application submitted\nView your applications", "fields": 1})[0]
    assert c({"text": "Thank you for applying! We have received your application.", "fields": 0})[0]
    assert c({"text": "Thank you", "fields": 0})[0] is False                              # too vague on its own
    ok, why = c({"text": "Application submitted", "fields": 12})
    assert not ok and "form still on screen" in why                                         # words in a banner above a live form
    assert not c({"text": "Your application could not be submitted. Please correct the required fields", "fields": 0})[0]
    assert not c({"text": "Fill in your details to submit your application", "fields": 8})[0]


@pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="browser")
def test_wait_for_confirmation_sees_a_page_that_confirms_after_a_delay_and_never_clicks():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.confirmation import wait_for_confirmation
    html = ("<form id=f><input name=a><input name=b><input name=c><input name=d><button id=go>Submit</button></form>"
            "<script>setTimeout(()=>{document.body.innerHTML='<h1>Thank you for applying</h1><p>Your application has been submitted.</p>'},1500)</script>")
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(); pg.set_content(html)
        ok, why = wait_for_confirmation(pg, timeout_s=8)
        assert ok and "applying" in why.lower()
        pg.set_content("<form><input name=a><input name=b><input name=c><input name=d><button>Submit</button></form>")
        assert wait_for_confirmation(pg, timeout_s=2)[0] is False
        b.close()


@pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="browser")
def test_read_form_values_returns_what_is_on_the_form_by_question():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.form_values import read_form_values
    html = ("<label>Full name <input value='Rakshit'></label><label>Source* <select><option>Select</option><option selected>LinkedIn</option></select></label>"
            "<label><input type=checkbox checked> Consider me for other roles</label><label><input type=checkbox> Newsletter</label>"
            "<div id=q>Notice period</div><div role=combobox aria-labelledby=q tabindex=0><span>30 days</span></div>"
            "<fieldset><legend>Gender</legend><label><input type=radio name=g checked> Male</label><label><input type=radio name=g> Female</label></fieldset>")
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(); pg.set_content(html)
        v = read_form_values(pg)
        assert v["Full name"] == "Rakshit" and v["Source*"] == "LinkedIn" and v["Notice period"] == "30 days"
        assert v["Consider me for other roles"] == "True" and v["Newsletter"] == "False" and v["Gender"] == "Male"
        b.close()


def test_ticked_applied_button_confirms_but_nav_link_does_not():
    from career_agent.browser.confirmation import confirmation_from_signals as c
    assert c({"text": "Home | Jobs | Applied | Messages | ✓  Applied | About", "fields": 0})[0]
    assert not c({"text": "Home | Jobs | Applied | Messages | Apply now", "fields": 0})[0]
