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


FORM = """<!doctype html><body><form>
  <input aria-label="First name"><input type="email" aria-label="Email Address"><button>Apply now</button>
</form></body>"""
EMAIL_STEP = """<!doctype html><body><form><input type="email" aria-label="Email Address"><button>Continue</button></form></body>"""
CAPTCHA = """<!doctype html><body><label><input type="checkbox"> I'm not a robot</label>
<textarea id="g-recaptcha-response" style="display:none"></textarea><button>Verify</button></body>"""
BIG = "width:600px;height:500px"


def _scan(pw, frames, stall=()):
    """A careers page (https://careers.test) with one <iframe> per entry in `frames`
    ({src, html, style}); served offline. `stall` = frame srcs whose request never answers.
    Returns (browser, page, labels read by perception)."""
    from career_agent.browser.perception import snapshot_form
    tags = "".join(f'<iframe src="{f["src"]}" style="{f.get("style", BIG)}"></iframe>' for f in frames)
    page_html = f'<!doctype html><html><body><h1>Careers</h1><input aria-label="Search jobs">{tags}</body></html>'
    bodies = {f["src"]: f["html"] for f in frames}
    browser = pw.chromium.launch()
    page = browser.new_page()

    def handle(route):
        url = route.request.url
        if url in stall:
            return                                  # never answered: a frame stuck loading
        body = bodies.get(url, page_html)
        route.fulfill(status=200, content_type="text/html", body=body)

    page.route("**/*", handle)
    page.goto("https://careers.test/jobs", wait_until="commit")
    page.wait_for_timeout(600)
    return browser, page, [f.label for f in snapshot_form(page)]


def test_scans_and_fills_inside_iframe():
    """A form embedded from a known ATS host: perception sees its fields (frame-qualified
    refs), the detector sees across frames, and the filler fills them."""
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form, frame_target
    from career_agent.browser.page_prep import is_application_form
    from career_agent.browser.filler import apply_decisions
    from career_agent.orchestrator.mapper import FillDecision

    src = "https://boards.greenhouse.io/embed/job_app?for=acme"
    with sync_playwright() as pw:
        browser, page, _ = _scan(pw, [{"src": src, "html": FORM}])
        fm = snapshot_form(page)
        iframe_fields = [f for f in fm if f.ref.startswith("f") and "@@" in f.ref]
        purposes = {f.purpose for f in fm}
        assert "email" in purposes and "first_name" in purposes
        assert iframe_fields, "expected frame-qualified refs for the iframe form"
        assert is_application_form(page)
        email = next(f for f in fm if f.purpose == "email")
        apply_decisions(page, [FillDecision(email.ref, "email", "Email", "me@example.com", "fill", "test")])
        target, sel = frame_target(page, email.ref)
        assert target.input_value(sel) == "me@example.com"
        browser.close()


def test_a_provider_that_is_not_on_any_list_is_still_read():
    """Swiggy's mynexthire (and any company's own embedded form) — the case the old host list missed."""
    from playwright.sync_api import sync_playwright
    for src in ("https://swiggy.mynexthire.com/employer/jobs/apply", "https://careers.acme.test/embed/apply"):
        with sync_playwright() as pw:
            browser, _, labels = _scan(pw, [{"src": src, "html": FORM}])
            browser.close()
        assert any("Email Address" in l for l in labels), src
        assert any("Search jobs" in l for l in labels)             # the page itself is still read


def test_a_first_step_that_only_asks_for_an_email_is_read():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _, labels = _scan(pw, [{"src": "https://jobs.acme.test/start", "html": EMAIL_STEP}])
        browser.close()
    assert any("Email Address" in l for l in labels)


def test_captcha_analytics_and_widget_frames_are_not_read():
    from playwright.sync_api import sync_playwright
    cases = [
        ("https://www.google.com/recaptcha/api2/anchor", FORM),     # denied by address, even with fields
        ("https://widgets.example.test/captcha", CAPTCHA),          # unknown address: no real fields
        ("https://widgets.example.test/tiny", FORM),                # unknown address, but sized like a pixel...
    ]
    for src, html in cases:
        style = "width:40px;height:40px" if src.endswith("/tiny") else BIG
        with sync_playwright() as pw:
            browser, _, labels = _scan(pw, [{"src": src, "html": html, "style": style}])
            browser.close()
        assert not any("Email Address" in l or "robot" in l for l in labels), src
        assert any("Search jobs" in l for l in labels), src


def test_a_hidden_frame_is_not_read():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _, labels = _scan(pw, [{"src": "https://jobs.acme.test/hidden", "html": FORM, "style": "display:none"}])
        browser.close()
    assert not any("Email Address" in l for l in labels)


def test_a_frame_that_never_finishes_loading_cannot_hang_the_run():
    import time
    from playwright.sync_api import sync_playwright
    stuck = "https://jobs.acme.test/stuck"
    with sync_playwright() as pw:
        t0 = time.monotonic()
        browser, _, labels = _scan(pw, [{"src": stuck, "html": FORM}], stall=(stuck,))
        took = time.monotonic() - t0
        browser.close()
    assert any("Search jobs" in l for l in labels)
    assert not any("Email Address" in l for l in labels)
    assert took < 15, f"took {took:.1f}s"


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
