import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1",
                                reason="set RUN_BROWSER_TESTS=1 to run")


def _url(name):
    return (Path(__file__).parent / "fixtures" / name).resolve().as_uri()


def _page(pw, name):
    b = pw.chromium.launch(); p = b.new_page(); p.goto(_url(name)); return b, p


def test_dismiss_consent_prefers_decline():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.page_prep import dismiss_consent
    with sync_playwright() as pw:
        b, p = _page(pw, "consent_decline.html")
        assert dismiss_consent(p) is True
        assert dismiss_consent(p) is False       # banner gone -> no-op
        b.close()


def test_dismiss_consent_accept_only_clicks_ok():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.page_prep import dismiss_consent
    with sync_playwright() as pw:
        b, p = _page(pw, "consent_accept_only.html")
        assert dismiss_consent(p) is True
        b.close()


def test_dismiss_dialogs_continue_working():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.page_prep import dismiss_dialogs
    with sync_playwright() as pw:
        b, p = _page(pw, "dialog_session.html")
        assert dismiss_dialogs(p) is True
        b.close()


def test_classify_entry():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.page_prep import classify_entry
    with sync_playwright() as pw:
        for name, expect in [("entry_password.html", "password"),
                             ("entry_email.html", "email_auth"),
                             ("entry_form.html", "form"),
                             ("entry_jd.html", "none")]:
            b, p = _page(pw, name)
            assert classify_entry(p) == expect, name
            b.close()


def test_enter_application_reaches_form():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.page_prep import enter_application
    with sync_playwright() as pw:
        b, p = _page(pw, "entry_apply.html")
        assert enter_application(p) == "form"
        b.close()


def test_wizard_step_is_the_form_but_search_page_is_not():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.page_prep import (
        _is_wizard_step, is_application_form, reach_application_form)
    with sync_playwright() as pw:
        # a wizard step (one screening question + Next) has no personal-info
        # fields, but IS the application form and reach() must hand it off
        b, p = _page(pw, "wizard_step.html")
        assert not is_application_form(p)         # no name/email/resume
        assert _is_wizard_step(p)                 # select + Next -> a form step
        assert reach_application_form(p) == (p, "form")
        b.close()
        # a job-search page (search field + Search button, no Next) is NOT a step
        b, p = _page(pw, "search_page.html")
        assert not _is_wizard_step(p)
        b.close()


def test_email_auth_email_to_otp_to_form():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.page_prep import email_auth
    with sync_playwright() as pw:
        b, p = _page(pw, "email_auth.html")
        got = {}
        def otp_reader():
            got["asked"] = True
            return "123456"
        res = email_auth(p, "me@example.com", otp_reader=otp_reader, on_captcha=None)
        assert got.get("asked") is True
        assert res == "form"
        assert p.locator('#em').input_value() == "me@example.com"
        assert p.locator('input[name="pin-code-1"]').input_value() == "1"
        b.close()
