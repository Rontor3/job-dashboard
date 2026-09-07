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


def test_scans_and_fills_inside_iframe():
    """The application form is inside a cross-origin-style <iframe>; perception
    must see its fields (frame-qualified refs) and the filler must fill them."""
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form
    from career_agent.browser.page_prep import is_application_form
    from career_agent.browser.filler import apply_decisions
    from career_agent.orchestrator.mapper import FillDecision

    url = (Path(__file__).parent / "fixtures" / "iframe_form.html").resolve().as_uri()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(url)
        page.wait_for_timeout(300)

        fm = snapshot_form(page)
        # the iframe's fields are present, and their refs are frame-qualified
        iframe_fields = [f for f in fm if f.ref.startswith("f") and "@@" in f.ref]
        purposes = {f.purpose for f in fm}
        assert "email" in purposes and "first_name" in purposes   # read from inside the frame
        assert iframe_fields, "expected frame-qualified refs for the iframe form"
        assert is_application_form(page)                          # detector sees across frames

        # fill an in-frame field via its frame-qualified ref, then read it back
        email = next(f for f in fm if f.purpose == "email")
        apply_decisions(page, [FillDecision(email.ref, "email", "Email",
                                            "me@example.com", "fill", "test")])
        from career_agent.browser.perception import frame_target
        target, sel = frame_target(page, email.ref)
        assert target.input_value(sel) == "me@example.com"
        browser.close()
