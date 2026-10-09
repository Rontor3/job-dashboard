"""A login page also shows an email box and a password box: it is NOT the registration form. With no account yet the
provider must go to the page's sign-up link (SuccessFactors: 'Create an account') instead of submitting generated
credentials into the login form."""
import os

import pytest

from career_agent.browser.credential_provider import _accept_consent_link, _is_login_form, login_form_from_signals

LOGIN = """<html><body><h1>Sign in</h1><form>
<label for="u">Email Address:*</label><input id="u" name="username" type="text">
<label for="p">Password:*</label><input id="p" name="password" type="password">
<button type="submit">Sign In</button></form><a href="#">Forgot your password?</a> <a href="#">Create an account</a></body></html>"""
REGISTER_CONFIRM = """<html><body><h1>Create account</h1><form>
<input name="email" type="email" placeholder="Email"><input name="password" type="password"><input name="confirm" type="password">
<button type="submit">Register</button></form></body></html>"""
REGISTER_NAMES = """<html><body><form><input name="firstName" placeholder="First name"><input name="lastName" placeholder="Last name">
<input name="email" type="email"><input name="password" type="password"><button type="submit">Create account</button></form></body></html>"""
SIMPLE_SIGNUP = """<html><body><h1>Join</h1><form><input name="email" type="email"><input name="password" type="password">
<button type="submit">Sign up</button></form><a href="#">Already have an account? Sign in</a></body></html>"""


def test_login_form_definition():
    assert login_form_from_signals({"passwordInputs": 1, "nameInputs": 0, "forgotCtl": True})
    assert login_form_from_signals({"passwordInputs": 1, "nameInputs": 0, "signInSubmit": True})
    assert not login_form_from_signals({"passwordInputs": 2, "nameInputs": 0, "forgotCtl": True})     # confirm password
    assert not login_form_from_signals({"passwordInputs": 1, "nameInputs": 1, "signInSubmit": True})  # name boxes
    assert not login_form_from_signals({"passwordInputs": 1, "nameInputs": 0})                         # no login-only cue
    assert not login_form_from_signals({})


@pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")
@pytest.mark.parametrize("html,expected", [(LOGIN, True), (REGISTER_CONFIRM, False), (REGISTER_NAMES, False),
                                           (SIMPLE_SIGNUP, False)])
def test_real_pages_login_vs_registration(html, expected):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.set_content(html)
        assert _is_login_form(page) is expected
        b.close()


def test_phone_parts_split_dial_code_and_national_number():
    from career_agent.browser.credential_provider import _phone_parts
    assert _phone_parts("+91 98765 43210") == ("+91", "9876543210")
    assert _phone_parts("98765 43210") == ("+91", "9876543210")          # no prefix: India
    assert _phone_parts("+1 415 555 0100") == ("+1", "4155550100")
    assert _phone_parts("") == ("+91", "")


SF_REGISTER = """<html><body><form>
<label for="e">Email Address: *</label><input id="e" name="fbclc_userName" type="text">
<label for="pw">Choose Password: *</label><input id="pw" name="fbclc_pwd" type="password">
<label for="p2">Retype Password: *</label><input id="p2" name="fbclc_pwdConf" type="password">
<label for="f">First Name: *</label><input id="f" name="fbclc_fName" type="text">
<label for="l">Last Name: *</label><input id="l" name="fbclc_lName" type="text">
<label for="c">Country/Region Code:*</label><select id="c" name="fbclc_ituCode"><option value="">- Select -</option>
  <option value="a">Afghanistan (+93)</option><option value="in">India (+91)</option><option value="us">United States (+1)</option></select>
<label for="ph">Phone Number:*</label><input id="ph" name="fbclc_phoneNumber" type="text">
<label for="r">Country/Region of Residence:</label><select id="r" name="fbclc_country"><option value="">- Select -</option>
  <option value="a">Afghanistan</option><option value="in">India</option></select>
<button type="submit">Create Account</button></form></body></html>"""


@pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")
def test_registration_form_gets_phone_dial_code_country_and_names_are_not_doubled():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.credential_provider import _fill_visible_fields
    cred = {"username": "a@b.co", "password": "Pw-123456!x", "first_name": "Rakshit", "last_name": "Singh",
            "phone": "+91 98765 43210"}
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.set_content(SF_REGISTER)
        _fill_visible_fields(page, cred)
        _fill_visible_fields(page, cred)                       # a second pass must not double anything
        v = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('input,select')].map(e => [e.name, e.value]))""")
        b.close()
    assert v["fbclc_fName"] == "Rakshit" and v["fbclc_lName"] == "Singh"
    assert v["fbclc_phoneNumber"] == "9876543210"
    assert v["fbclc_ituCode"] == "in" and v["fbclc_country"] == "in"
    assert v["fbclc_userName"] == "a@b.co" and v["fbclc_pwd"] == v["fbclc_pwdConf"] == "Pw-123456!x"


@pytest.mark.skipif(not os.environ.get("RUN_BROWSER_TESTS"), reason="browser")
def test_consent_link_dialog_is_accepted():
    from playwright.sync_api import sync_playwright
    html = ("<a id=l onclick=\"document.getElementById('d').style.display='block';return false\">"
            "Read and accept the data privacy statement.</a>"
            "<div id=d style='display:none'><p>Notice</p><button onclick=\"document.getElementById('d').style.display='none';"
            "document.title='accepted'\">Accept</button><button>Decline</button></div>")
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(); pg.set_content(html)
        assert _accept_consent_link(pg) and pg.title() == "accepted"
        b.close()


@pytest.mark.skipif(not os.environ.get("RUN_BROWSER_TESTS"), reason="browser")
def test_registration_offered_as_alternative_options_takes_the_manual_one(monkeypatch):
    from types import SimpleNamespace
    from playwright.sync_api import sync_playwright
    from career_agent.browser import credential_provider as cp
    monkeypatch.setattr(cp, "_time", SimpleNamespace(sleep=lambda s: None))
    from career_agent.browser.credential_provider import _SIGNUP_TEXTS, _REGISTRATION_OPTIONS, _navigate_to_form, _registration_options_offered
    html = ("<main><h2>Log in</h2><input type=email><input type=password><button>Log in</button><a href=#>Forgot your password?</a>"
            "<p>Create an account using any of the following options:</p>"
            "<a href=# onclick=\"document.title='file'\">Upload file</a><a href=# onclick=\"document.title='manual'\">Self-complete</a>"
            "<a href=# onclick=\"document.title='later'\">Upload CV later</a></main>")
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(); pg.set_content(html)
        assert not _navigate_to_form(pg, _SIGNUP_TEXTS, "sign-up form")           # no 'sign up' link on this page
        assert _registration_options_offered(pg)
        assert _navigate_to_form(pg, _REGISTRATION_OPTIONS, "manual registration option") and pg.title() == "manual"
        b.close()


@pytest.mark.skipif(not os.environ.get("RUN_BROWSER_TESTS"), reason="browser")
def test_manual_option_that_opens_a_profile_form_without_password_is_handed_to_the_filler(tmp_path, monkeypatch):
    from playwright.sync_api import sync_playwright
    from career_agent.browser import credential_provider as cp
    monkeypatch.setattr(cp, "CRED_PATH", tmp_path / "creds.json", raising=False)
    from types import SimpleNamespace
    monkeypatch.setattr(cp, "_time", SimpleNamespace(sleep=lambda s: None))
    html = ("<main><h2>Log in</h2><input type=email><input type=password><button>Log in</button><a href=#>Forgot your password?</a>"
            "<p>Create an account using any of the following options:</p><a role=button href=# id=m "
            "onclick=\"document.body.innerHTML='<h1>Profile information</h1><input type=email><input name=first_name><input name=last_name><button>Continue</button>';return false\">Self-complete</a></main>")
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(); pg.set_content(html)
        ok, action = cp.provide(pg, "password", "careers.example.com", email="a@b.co")
        assert ok and action == "register_inline"
        assert not (tmp_path / "creds.json").exists()
        b.close()


@pytest.mark.skipif(not os.environ.get("RUN_BROWSER_TESTS"), reason="browser")
def test_credentials_inside_a_long_application_form_are_not_submitted_early():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.credential_provider import _fill_wall, _is_combined_form
    rows = "".join(f"<input name=f{i} placeholder=f{i}>" for i in range(8))
    long_form = ("<form onsubmit=\"document.title='submitted';return false\"><input type=email name=email><input name=first_name>"
                 "<input name=last_name>" + rows + "<input type=password name=pw><input type=password name=pw2><button>Continue</button></form>")
    short = "<form onsubmit=\"document.title='submitted';return false\"><input type=email><input type=password><button>Sign in</button></form>"
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page()
        pg.set_content(long_form); assert _is_combined_form(pg)
        _fill_wall(pg, "password", {"username": "a@b.co", "password": "Pw#12345", "first_name": "A", "last_name": "B"}, site="x.example")
        assert pg.title() != "submitted" and pg.input_value("[name=pw]") == "Pw#12345"
        pg.set_content(short); assert not _is_combined_form(pg)
        b.close()


@pytest.mark.skipif(not os.environ.get("RUN_BROWSER_TESTS"), reason="browser")
def test_a_click_that_starts_a_slow_navigation_is_clicked_once():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.credential_provider import _safe_click
    home = "<a id=go href='/slow'>go</a><a id=other href='/other' style='position:absolute;left:0;top:0'>x</a>"
    hits = []

    def serve(route):
        if not route.request.url.endswith("/slow"):                 # /slow never answers: the navigation stays pending
            route.fulfill(content_type="text/html", body=home)

    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page()
        pg.route("http://agent.test/**", serve)
        pg.goto("http://agent.test/")
        pg.on("request", lambda r: hits.append(r.url) if r.resource_type == "document" else None)
        with pg.expect_request("**/slow"):
            assert _safe_click(pg.query_selector("#go"), timeout_ms=1500)
        assert [u for u in hits if u.endswith("/slow")] == ["http://agent.test/slow"]
        assert not any(u.endswith("/other") for u in hits)
        b.close()
