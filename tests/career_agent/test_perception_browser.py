import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_TESTS") != "1",
    reason="set RUN_BROWSER_TESTS=1 and `playwright install chromium` to run",
)


def _fixture_url():
    p = Path(__file__).parent / "fixtures" / "sample_form.html"
    return p.resolve().as_uri()


def test_snapshot_form_reads_fixture():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(_fixture_url())
        fm = snapshot_form(page)
        browser.close()

    by_purpose = {f.purpose for f in fm}
    assert "full_name" in by_purpose
    assert "email" in by_purpose
    assert "resume_upload" in by_purpose
    assert "attestation" in by_purpose
    assert any(f.kind == "radio_group" for f in fm)
