"""Zoho Recruit (live 2026-10-31): 'CAPTCHA *' / 'Type below image text' under a distorted-word image."""
import os

import pytest


def test_image_captcha_signal_is_a_submit_gate():
    from career_agent.browser.gate_probe import HANDLERS, classify_from_signals
    assert classify_from_signals({"image_captcha": True}) == "image_captcha"
    assert HANDLERS["image_captcha"] == "escalate"            # the human's, never solved


def test_the_captcha_box_never_reaches_an_answer_tier():
    from career_agent.browser.form_model import Field
    from career_agent.browser.page_prep import suppress_noise
    kept = suppress_noise([Field("#c", "text", "CAPTCHA *", True), Field("#t", "text", "Type below image text", True),
                           Field("#n", "text", "First Name", True)])
    assert [f.ref for f in kept] == ["#n"]


@pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")
def test_a_typed_image_captcha_at_the_foot_of_a_long_form_is_seen():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.gate_probe import classify_gate
    page_html = ('<div style="height:3000px"><input name="first"></div>'
                 '<div><label>CAPTCHA *</label><div><input placeholder="Type below image text">'
                 '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" width="80" height="30"></div></div>')
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.set_content(page_html)
        before = classify_gate(page)
        page.fill('input[placeholder]', 'abcd')                   # the human typed it
        after = classify_gate(page)
        b.close()
    assert (before, after) == ("image_captcha", "none")
