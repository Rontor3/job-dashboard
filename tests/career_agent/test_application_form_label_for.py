"""A form whose boxes carry their meaning only in <label for> text (SuccessFactors: fbclc_userName / fbclc_fName) is
still an application form. Before, it counted 1 real field, so Wipro's register+apply page was read as a bare login
wall and the run stopped auth_wall (job 31385, live 2026-10-22)."""
import os

import pytest

from career_agent.browser.page_prep import is_application_form
from test_cred_login_vs_register import SF_REGISTER

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")

LABEL_ONLY_SEARCH = """<html><body><label for="q">Search jobs</label><input id="q" name="q" type="text"></body></html>"""


@pytest.mark.parametrize("html,expected", [(SF_REGISTER, True), (LABEL_ONLY_SEARCH, False)])
def test_label_for_text_counts(html, expected):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.set_content(html)
        assert is_application_form(page) is expected
        b.close()
