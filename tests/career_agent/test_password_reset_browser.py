"""A refused login with the email filled in is recovered by Forgot password -> reset link -> new password -> sign in
(NatWest Workday 2026-11-02). Offline: a fake site, Gmail stubbed to return that site's reset link."""
import json
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")

LOGIN = """<h2>Sign In</h2><div id=err></div>
<label for=e>Email Address*</label><input type=text id=e>
<label for=p>Password*</label><input type=password id=p>
<button type=submit onclick="event.preventDefault(); const ok = localStorage.pw && p.value === localStorage.pw;
  if (ok) location.href='/home'; else err.textContent='You may have entered the wrong email address or password';">Sign In</button>
<a href="/forgot">Forgot your password?</a>"""
FORGOT = """<h2>Reset your password</h2><label for=fe>Email Address*</label><input type=text id=fe>
<button type=submit onclick="event.preventDefault(); localStorage.asked = fe.value; document.body.innerHTML='Check your email';">Submit</button>"""
RESET = """<h2>Choose a new password</h2><label for=n1>New Password</label><input type=password id=n1>
<label for=n2>Confirm Password</label><input type=password id=n2>
<button type=submit onclick="event.preventDefault(); if (n1.value === n2.value && n1.value) { localStorage.pw = n1.value;
  document.body.innerHTML='Password changed'; }">Reset Password</button>"""


def test_a_refused_login_is_recovered_by_a_password_reset(tmp_path, monkeypatch):
    from playwright.sync_api import sync_playwright
    from career_agent.browser import credential_provider as cp
    from career_agent.integrations import gmail_otp
    from career_agent.browser.password_reset import reset_password
    monkeypatch.setattr(cp, "_STORE", tmp_path / "creds.json")
    monkeypatch.setattr(cp, "_observe_until_change", lambda page, label, *a, **k: "unknown")
    monkeypatch.setattr(gmail_otp, "available", lambda: True)
    asked = []
    monkeypatch.setattr(gmail_otp, "poll_verify_link",
                        lambda site, after, timeout_s=90: asked.append(site) or "https://site.test/reset?token=abc")
    pages = {"/login": LOGIN, "/forgot": FORGOT, "/reset": RESET, "/home": "<h1>Welcome back</h1>"}
    cred = {"username": "me@example.com", "password": "Old#pass1"}
    cp.save_credential("site.test", cred["username"], cred["password"])
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page()
        page.route("https://site.test/**", lambda r: r.fulfill(
            status=200, content_type="text/html", body=pages.get(r.request.url.split("site.test")[1].split("?")[0], "")))
        page.goto("https://site.test/login")
        new = reset_password(page, cred, "site.test", wait_s=1)
        assert new and new["password"] != "Old#pass1"
        assert page.evaluate("localStorage.asked") == "me@example.com" and asked == ["site.test"]
        assert page.evaluate("localStorage.pw") == new["password"]          # the site took the new password
        assert page.url.endswith("/login")                                  # back to sign in
        stored = json.loads((tmp_path / "creds.json").read_text())
        b.close()
    assert stored["site.test"]["password"] == new["password"]               # saved
    assert stored["site.test:stale"]["password"] == "Old#pass1"             # the refused one kept as history
