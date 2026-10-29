"""A résumé upload counts only when the file shows on the page."""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")


def test_resume_took_only_when_the_file_shows(tmp_path):
    from playwright.sync_api import sync_playwright
    from career_agent.browser.filler import resume_took

    pdf = tmp_path / "Rakshit_Singh_Resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page()
        page.set_content('<input type=file id=f>')
        assert resume_took(page, pdf, wait_ms=1000) is False
        page.set_input_files("#f", str(pdf))
        assert resume_took(page, pdf, wait_ms=1000) is True
        b.close()
