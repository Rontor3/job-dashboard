import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1",
                                reason="set RUN_BROWSER_TESTS=1 to run")


def _url(name):
    return (Path(__file__).parent / "fixtures" / name).resolve().as_uri()


def test_greenhouse_style_labels_are_captured():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.goto(_url("greenhouse_labels.html"))
        labels = [f.label for f in snapshot_form(page) if f.kind != "button"]
        b.close()
    assert any("Country" in l for l in labels)
    assert any("education" in l.lower() for l in labels)
    assert any("LinkedIn" in l for l in labels)
    assert "" not in labels          # no empty-label inputs
