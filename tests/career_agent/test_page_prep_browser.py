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
