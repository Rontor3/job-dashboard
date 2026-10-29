"""A chat-only apply page is handed to the human; a real form or a Workday-like list is not."""
import os

import pytest

from career_agent.browser.page_prep import is_chat_apply

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")

CHAT = '<div role="log"><p>Hi! I\'m the recruiting assistant.</p></div><textarea></textarea><button>Send</button>'
FORM = '<form><input id=a><input id=b><input id=c><button>Next</button></form>'
WORKDAY_LIKE = ('<input type=text><div aria-live="polite"><div>0 items selected</div></div>'
                '<button>Search</button>')


def _check(html):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.set_content(f"<html><body>{html}</body></html>")
        got = is_chat_apply(page)
        b.close()
    return got


def test_chat_page_is_chat_apply():
    assert _check(CHAT) is True


def test_form_is_not_chat_apply():
    assert _check(FORM) is False


def test_single_box_with_aria_live_is_not_chat_apply():
    assert _check(WORKDAY_LIKE) is False


# FedEx (live 2026-10-29): a language picker beside the chat, a hidden file box, no [role=log] — only the composer
CHAT_WITH_PICKER = ('<input type=text placeholder="Select"><input type=file style="display:none">'
                    '<div class="composer"><textarea placeholder="Write a reply..."></textarea>'
                    '<button aria-label="Send message">→</button></div>')
CONTACT_FORM = ('<form><input placeholder=Name><input type=email placeholder=Email><textarea></textarea>'
                '<button>Send</button></form>')


def test_composer_beside_a_picker_is_chat_apply():
    assert _check(CHAT_WITH_PICKER) is True


def test_contact_form_with_send_is_not_chat_apply():
    assert _check(CONTACT_FORM) is False
