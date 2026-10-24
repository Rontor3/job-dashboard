"""Workday (Opella / Hitachi, live 2026-10-24): the résumé goes straight into the page's hidden file input (the
attached Chrome's native chooser never reached it), never into a cover-letter or photo slot; and an open dropdown
is closed before the advance click retries (it hid 'Save and Continue' from the accessibility tree)."""
import os
from types import SimpleNamespace as NS

import pytest

from career_agent.orchestrator.browser_deps import _close_open_list

WORKDAY = """<html><body><div data-automation-id="resumeUpload">Upload your resume / CV<button>Select file</button>
<input type="file" data-automation-id="file-upload-input-ref" style="display:none"></div></body></html>"""
COVER_ONLY = """<html><body><div>Attach a cover letter<input type="file" name="coverLetter"></div></body></html>"""


@pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")
def test_the_resume_goes_into_the_pages_file_input(tmp_path):
    from playwright.sync_api import sync_playwright
    from career_agent.browser.filler import upload_resume_to_input
    pdf = tmp_path / "Rakshit_Singh_Resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    with sync_playwright() as pw:
        b = pw.chromium.launch(); pg = b.new_page()
        pg.set_content(WORKDAY)
        assert upload_resume_to_input(pg, str(pdf)) == "file-upload-input-ref"
        assert pg.evaluate("document.querySelector('input[type=file]').files[0].name") == "Rakshit_Singh_Resume.pdf"
        pg.set_content(COVER_ONLY)
        assert upload_resume_to_input(pg, str(pdf)) is None              # a lone cover-letter slot is not the résumé's
        b.close()


def test_an_open_list_is_closed_but_never_inside_a_dialog():
    pressed = []
    _close_open_list(NS(evaluate=lambda js: True, keyboard=NS(press=pressed.append), wait_for_timeout=lambda ms: None))
    assert pressed == ["Escape"]
    pressed.clear()
    _close_open_list(NS(evaluate=lambda js: False, keyboard=NS(press=pressed.append), wait_for_timeout=lambda ms: None))
    assert pressed == []
