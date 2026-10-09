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


class _PolledPage:
    """Answers each poll with the next page state; has no click method, so any click attempt fails the test."""
    frames = []

    def __init__(self, states):
        self.states, self.waits = iter(states), 0

    def evaluate(self, js):
        return next(self.states)

    def wait_for_timeout(self, ms):
        self.waits += 1


def test_wait_for_confirmation_sees_a_page_that_confirms_after_a_delay_and_never_clicks():
    from career_agent.browser.confirmation import wait_for_confirmation
    form = {"text": "Apply\nSubmit", "fields": 4}
    pg = _PolledPage([form, form, {"text": "Thank you for applying! Your application has been submitted.", "fields": 0}])
    ok, why = wait_for_confirmation(pg, timeout_s=8)
    assert ok and "applying" in why.lower() and pg.waits == 2
    pg = _PolledPage([form] * 10)
    assert wait_for_confirmation(pg, timeout_s=2) == (False, "no confirmation text") and pg.waits == 3


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
