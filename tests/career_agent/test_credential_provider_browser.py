import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_TESTS") != "1",
    reason="set RUN_BROWSER_TESTS=1 to run",
)


def _fixture_url(name):
    return (Path(__file__).parent / "fixtures" / name).resolve().as_uri()


def test_form_already_visible_on_workday_style_page():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.credential_provider import _form_already_visible

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(_fixture_url("workday_create_account.html"))
        result = _form_already_visible(page)
        browser.close()

    assert result is True


def test_fill_visible_fields_checks_consent_and_both_passwords():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.credential_provider import _fill_visible_fields

    cred = {"username": "a@b.com", "password": "Xy9!abcd"}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(_fixture_url("workday_create_account.html"))
        _fill_visible_fields(page, cred)
        email_val = page.input_value("#email")
        pw1_val = page.input_value("#pw")
        pw2_val = page.input_value("#pw2")
        consent_checked = page.is_checked("#consent")
        browser.close()

    assert email_val == "a@b.com"
    assert pw1_val == "Xy9!abcd"
    assert pw2_val == "Xy9!abcd"
    assert consent_checked is True


def test_navigate_to_form_skips_header_chrome_prefers_in_form_link():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.credential_provider import _navigate_to_form

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(_fixture_url("workday_create_account.html"))
        found = _navigate_to_form(page, ["sign in"], "login form")
        # the header's #chrome-signin has no click handler that changes the DOM;
        # only the in-form #inform-signin toggles a marker we can check for.
        clicked_in_form = page.evaluate(
            "document.getElementById('inform-signin').dataset.clicked === '1'"
        )
        browser.close()

    assert found is True
    assert clicked_in_form is True


def test_a_hidden_privacy_checkbox_is_ticked_through_its_label():
    """Oracle email-first: the real box is hidden; Next does nothing until it is ticked (Cummins, live 2026-10-18)."""
    from playwright.sync_api import sync_playwright
    from career_agent.browser.credential_provider import _check_consent_checkboxes

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(_fixture_url("oracle_email_first_consent.html"))
        page.fill("#email", "a@b.com")
        assert _check_consent_checkboxes(page) == 1
        page.click("#next")
        moved = page.locator("#otp").count() == 1
        browser.close()
    assert moved
