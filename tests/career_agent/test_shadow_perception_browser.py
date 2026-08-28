import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1",
                                reason="set RUN_BROWSER_TESTS=1 to run")


def _url(name):
    return (Path(__file__).parent / "fixtures" / name).resolve().as_uri()


def test_perception_pierces_shadow_dom():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.goto(_url("shadow_form.html"))
        form = snapshot_form(page)
        labels = [f.label for f in form]
        kinds = {f.label: f.kind for f in form}
        b.close()
    # light-DOM field still seen
    assert any("Light DOM search" in l for l in labels)
    # shadow-DOM fields now seen
    assert any("Email address" in l for l in labels)
    assert kinds.get("Email address") == "email"
    assert any("Why this role" in l for l in labels)
    # NESTED shadow root reached
    assert any("Phone number" in l for l in labels)
    # shadow button captured
    assert any(l == "Submit application" and kinds[l] == "button" for l in labels)
