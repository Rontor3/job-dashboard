"""Zoho Recruit candidate portal (Training Basket, live 2026-10-29): the Login box sits in a same-site frame."""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")

MAIN = """<h1>Candidate Portal</h1><iframe src="{frame}" style="width:400px;height:200px"></iframe>
<p>Do not have an account? <a href="javascript:;">Create an account</a></p>"""
LOGIN = """<label for="u">Login</label><input id="login_id" type="text" name="LOGIN_ID"><button>Login</button>
<a href="#">Forgot Password?</a>"""


def _classify(frame_url):
    from playwright.sync_api import sync_playwright
    from career_agent.browser.page_prep import classify_entry
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page()
        page.route("https://portal.example.com/**", lambda r: r.fulfill(
            content_type="text/html", body=MAIN.format(frame=frame_url) if "portal?" in r.request.url else LOGIN))
        page.route("https://other.example.org/**", lambda r: r.fulfill(content_type="text/html", body=LOGIN))
        page.goto("https://portal.example.com/portal?source=career"); page.wait_for_timeout(800)
        kind = classify_entry(page)
        b.close()
    return kind


def test_a_same_site_framed_sign_in_is_the_wall():
    assert _classify("https://portal.example.com/accounts/p/1/signin?_embed=true") == "email_auth"


def test_another_sites_frame_is_not_this_pages_wall():
    assert _classify("https://other.example.org/signin") != "email_auth"
