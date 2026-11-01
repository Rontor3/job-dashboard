"""A sign-in page with email AND password together, the email box named only by its label (Workday: type=text,
id=input-4): the 'password' state fills every box, not only the password (NatWest 2026-11-02)."""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")

PAGE = """<h2>Sign In</h2>
<label for="input-4">Email Address*</label><input type="text" id="input-4" autocomplete="email">
<label for="input-5">Password*</label><input type="password" id="input-5">
<label for="hp">Enter website. This input is for robots only</label><input type="text" id="hp" name="website" style="position:absolute;left:-9999px">
<button type="button" onclick="document.body.dataset.sent=1">Sign In</button>"""


def test_the_password_state_fills_the_email_too(monkeypatch):
    from playwright.sync_api import sync_playwright
    from career_agent.browser import credential_provider as cp
    monkeypatch.setattr(cp, "_observe_until_change", lambda page, label, *a, **k: "unknown")
    cred = {"username": "me@example.com", "password": "Pw#123456"}
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.set_content(PAGE)
        assert cp._classify_page_state(page) == "password"
        assert cp._email_box_empty(page)                          # a 'rejected' login here says nothing about the password
        cp._handle_state(page, "password", cred, "site.test")
        got = page.evaluate("[document.getElementById('input-4').value, document.getElementById('input-5').value, document.getElementById('hp').value]")
        assert not cp._email_box_empty(page)
        b.close()
    assert got == ["me@example.com", "Pw#123456", ""]             # the robots-only box stays empty
