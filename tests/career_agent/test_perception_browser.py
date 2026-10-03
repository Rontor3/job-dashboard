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


_FORM_FRAME = """<!doctype html><body><form>
  <input aria-label="First name"><input type="email" aria-label="Email Address"><button>Apply now</button>
</form></body>"""


def _page_with_embedded_form(pw, frame_src):
    """A careers page whose application form lives in an <iframe src=frame_src>,
    served offline: the page from careers.test, the frame from wherever frame_src points."""
    html = (f'<!doctype html><html><body><h1>Careers</h1><input aria-label="Search jobs">'
            f'<iframe id="ats" src="{frame_src}"></iframe></body></html>')
    browser = pw.chromium.launch()
    page = browser.new_page()
    page.route("**/*", lambda route: route.fulfill(
        status=200, content_type="text/html",
        body=_FORM_FRAME if "/embed" in route.request.url else html))
    page.goto("https://careers.test/jobs")
    page.wait_for_timeout(300)
    return browser, page


def test_scans_and_fills_inside_iframe():
    """The application form is inside an embedded ATS <iframe> (a known job-site
    host); perception must see its fields (frame-qualified refs) and the filler
    must fill them."""
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form
    from career_agent.browser.page_prep import is_application_form
    from career_agent.browser.filler import apply_decisions
    from career_agent.orchestrator.mapper import FillDecision

    with sync_playwright() as pw:
        browser, page = _page_with_embedded_form(pw, "https://boards.greenhouse.io/embed/job_app?for=acme")
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


def test_frames_from_unknown_hosts_are_not_scanned():
    """Ad / analytics / widget frames are skipped on purpose: evaluating in one can
    block indefinitely (perception._ATS_FRAME_HOSTS)."""
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form

    with sync_playwright() as pw:
        browser, page = _page_with_embedded_form(pw, "https://widgets.example.net/embed/chat")
        labels = [f.label for f in snapshot_form(page)]
        browser.close()
    assert any("Search jobs" in l for l in labels)            # the page itself is still read
    assert not any("Email Address" in l for l in labels)      # the unknown frame is not


def test_aria_role_radio_buttons_group_with_clean_labels():
    """Typeform-style <button role=radio> choice buttons (no native <input
    type=radio>) must group into one radio_group Field, and the aria-hidden
    keyboard-shortcut badge ("KeyA") must not pollute the option/question text."""
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form

    url = (Path(__file__).parent / "fixtures" / "aria_radio_choice.html").resolve().as_uri()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(url)
        fm = snapshot_form(page)
        browser.close()

    groups = [f for f in fm if f.kind == "radio_group"]
    assert len(groups) == 1
    g = groups[0]
    assert g.label == "What's your total experience?"
    assert g.options == ["0-1 year", "2-3 year", "4-5 year"]
    assert g.required is True
