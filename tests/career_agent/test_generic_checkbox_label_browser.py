import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1",
                                reason="set RUN_BROWSER_TESTS=1 to run")


def test_generic_checkbox_name_falls_back_to_the_consent_text():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form
    url = (Path(__file__).parent / "fixtures" / "privacy_generic_checkbox.html").resolve().as_uri()
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.goto(url)
        boxes = [f for f in snapshot_form(page, scroll=False) if f.kind == "checkbox"]
        b.close()
    assert len(boxes) == 1
    assert boxes[0].label != "Checkbox field"
    assert "I Agree" in boxes[0].label
