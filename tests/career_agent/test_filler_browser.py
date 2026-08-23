import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_TESTS") != "1",
    reason="set RUN_BROWSER_TESTS=1 to run",
)


def _fixture_url():
    return (Path(__file__).parent / "fixtures" / "sample_form.html").resolve().as_uri()


def test_fill_then_readback_matches():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form
    from career_agent.browser.filler import apply_decisions, read_back
    from career_agent.orchestrator.mapper import map_fields

    profile = {"full_name": "Jane Q", "email": "jane@example.com"}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(_fixture_url())
        form = snapshot_form(page)
        decisions = map_fields(form, profile, None)
        apply_decisions(page, decisions)
        values = read_back(page, decisions)
        browser.close()

    assert values["#name"] == "Jane Q"
    assert values["#email"] == "jane@example.com"
