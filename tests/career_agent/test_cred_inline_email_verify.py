"""An inline email-verification sign-up (email box + 'Send verification code' + 'Verify code', then the account
fields) is driven through: the code is requested, fetched, typed and verified before the account form is created.
Browser test: RUN_BROWSER_TESTS=1."""
import os

import pytest

PAGE = """<html><body><h1>Accenture Careers Application</h1>
<p>Register to start your application. Verify your email</p><form>
<input id="email" type="text" placeholder="user@email.com">
<button type="button" id="send" onclick="document.getElementById('codeRow').style.display='block'">SEND VERIFICATION CODE</button>
<div id="codeRow" style="display:none"><input id="verificationCode" type="text">
  <button type="button" id="verify" onclick="document.getElementById('create').disabled=false">VERIFY CODE</button></div>
<input id="givenName" type="text" placeholder="First Name"><input id="surname" type="text" placeholder="Last Name">
<select id="country"><option>India</option><option>United States</option></select>
<input id="newPassword" type="password"><input id="reenterPassword" type="password">
<input type="checkbox" id="consent"><label for="consent">I agree to the privacy policy</label>
<button type="submit" id="create" disabled onclick="event.preventDefault();document.body.insertAdjacentHTML('beforeend','<p>Account created</p>')">CREATE</button>
</form></body></html>"""


@pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")
def test_inline_email_verification_is_driven_through(tmp_path, monkeypatch):
    from playwright.sync_api import sync_playwright
    import career_agent.browser.credential_provider as cp
    import career_agent.integrations.gmail_otp as gmail

    store = tmp_path / "credentials.json"
    monkeypatch.setattr(cp, "_STORE", store)
    requested = []
    monkeypatch.setattr(gmail, "available", lambda: True)
    monkeypatch.setattr(gmail, "poll_otp", lambda **kw: requested.append(kw) or "482913")
    cred = {"username": "rakshit@example.com", "password": "Pw-123456!x", "label": "accenture",
            "first_name": "Rakshit", "last_name": "Singh"}

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.set_content(PAGE)
        assert cp._classify_page_state(page) == "inline_verify"       # not "otp", despite the button text
        cp._fill_wall(page, "accenture", cred, site="accenture.com")
        assert len(requested) == 1                                     # one code requested, from Gmail
        assert page.input_value("#email") == cred["username"]
        assert page.input_value("#verificationCode") == "482913"
        assert page.is_enabled("#create")
        assert page.inner_text("body").count("Account created") == 1
        b.close()
    saved = cp.load_credential("accenture.com", label="accenture")
    assert saved and saved["username"] == cred["username"]
