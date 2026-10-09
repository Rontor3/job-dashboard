import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_TESTS") != "1",
    reason="set RUN_BROWSER_TESTS=1 and `playwright install chromium` to run",
)


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.launch()
    yield b
    b.close()
    pw.stop()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


def _fixture_url():
    p = Path(__file__).parent / "fixtures" / "sample_form.html"
    return p.resolve().as_uri()


def test_snapshot_form_reads_fixture(page):
    from career_agent.browser.perception import snapshot_form

    page.goto(_fixture_url())
    fm = snapshot_form(page)

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


def _scan(page, frames, stall=()):
    """A careers page (https://careers.test) with one <iframe> per entry in `frames`
    ({src, html, style}); served offline. `stall` = frame srcs whose request never answers.
    Returns the form model perception reads once every answering frame has loaded."""
    from career_agent.browser.perception import snapshot_form
    tags = "".join(f'<iframe src="{f["src"]}" style="{f.get("style", BIG)}"></iframe>' for f in frames)
    page_html = f'<!doctype html><html><body><h1>Careers</h1><input aria-label="Search jobs">{tags}</body></html>'
    bodies = {f["src"]: f["html"] for f in frames}

    def handle(route):
        url = route.request.url
        if url in stall:
            return                                  # never answered: a frame stuck loading
        body = bodies.get(url, page_html)
        route.fulfill(status=200, content_type="text/html", body=body)

    page.route("**/*", handle)
    page.goto("https://careers.test/jobs", wait_until="domcontentloaded")
    for src in bodies.keys() - set(stall):
        for _ in range(250):
            if page.frame(url=src):
                break
            page.wait_for_timeout(20)
        page.frame(url=src).wait_for_load_state("domcontentloaded", timeout=5000)
    return snapshot_form(page)


def _labels(fm):
    return [f.label for f in fm]


def test_scans_and_fills_inside_iframe(page):
    """A form embedded from a known ATS host: perception sees its fields (frame-qualified
    refs), the detector sees across frames, and the filler fills them."""
    from career_agent.browser.perception import frame_target
    from career_agent.browser.page_prep import is_application_form
    from career_agent.browser.filler import apply_decisions
    from career_agent.orchestrator.mapper import FillDecision

    fm = _scan(page, [{"src": "https://boards.greenhouse.io/embed/job_app?for=acme", "html": FORM}])
    iframe_fields = [f for f in fm if f.ref.startswith("f") and "@@" in f.ref]
    purposes = {f.purpose for f in fm}
    assert "email" in purposes and "first_name" in purposes
    assert iframe_fields, "expected frame-qualified refs for the iframe form"
    assert is_application_form(page)
    email = next(f for f in fm if f.purpose == "email")
    apply_decisions(page, [FillDecision(email.ref, "email", "Email", "me@example.com", "fill", "test")])
    target, sel = frame_target(page, email.ref)
    assert target.input_value(sel) == "me@example.com"


@pytest.mark.parametrize("src", ["https://swiggy.mynexthire.com/employer/jobs/apply", "https://careers.acme.test/embed/apply"],
                         ids=["mynexthire", "own-domain"])
def test_a_provider_that_is_not_on_any_list_is_still_read(page, src):
    """Swiggy's mynexthire (and any company's own embedded form) — the case the old host list missed."""
    labels = _labels(_scan(page, [{"src": src, "html": FORM}]))
    assert any("Email Address" in l for l in labels)
    assert any("Search jobs" in l for l in labels)             # the page itself is still read


def test_a_first_step_that_only_asks_for_an_email_is_read(page):
    labels = _labels(_scan(page, [{"src": "https://jobs.acme.test/start", "html": EMAIL_STEP}]))
    assert any("Email Address" in l for l in labels)


@pytest.mark.parametrize("src,html,style", [
    ("https://www.google.com/recaptcha/api2/anchor", FORM, BIG),                 # denied by address, even with fields
    ("https://widgets.example.test/captcha", CAPTCHA, BIG),                      # unknown address: no real fields
    ("https://widgets.example.test/tiny", FORM, "width:40px;height:40px"),       # unknown address, but sized like a pixel
], ids=["recaptcha", "captcha-widget", "pixel-sized"])
def test_captcha_analytics_and_widget_frames_are_not_read(page, src, html, style):
    labels = _labels(_scan(page, [{"src": src, "html": html, "style": style}]))
    assert not any("Email Address" in l or "robot" in l for l in labels)
    assert any("Search jobs" in l for l in labels)


def test_a_hidden_frame_is_not_read(page):
    labels = _labels(_scan(page, [{"src": "https://jobs.acme.test/hidden", "html": FORM, "style": "display:none"}]))
    assert not any("Email Address" in l for l in labels)


def test_a_frame_that_never_finishes_loading_cannot_hang_the_run(page):
    import time
    stuck = "https://jobs.acme.test/stuck"
    t0 = time.monotonic()
    labels = _labels(_scan(page, [{"src": stuck, "html": FORM}], stall=(stuck,)))
    took = time.monotonic() - t0
    assert any("Search jobs" in l for l in labels)
    assert not any("Email Address" in l for l in labels)
    assert took < 15, f"took {took:.1f}s"


def test_aria_role_radio_buttons_group_with_clean_labels(page):
    """Typeform-style <button role=radio> choice buttons (no native <input
    type=radio>) must group into one radio_group Field, and the aria-hidden
    keyboard-shortcut badge ("KeyA") must not pollute the option/question text."""
    from career_agent.browser.perception import snapshot_form

    page.goto((Path(__file__).parent / "fixtures" / "aria_radio_choice.html").resolve().as_uri())
    groups = [f for f in snapshot_form(page) if f.kind == "radio_group"]
    assert len(groups) == 1
    g = groups[0]
    assert g.label == "What's your total experience?"
    assert g.options == ["0-1 year", "2-3 year", "4-5 year"]
    assert g.required is True


def test_react_readonly_radios_and_aria_required_are_perceived(page):
    from career_agent.browser.perception import snapshot_form

    page.set_content("<div role=radiogroup><b>Gender</b>"
                     + "".join(f"<input type=radio name=g value='{v}' readonly aria-required=true aria-label='{v}, Gender question'>" for v in ("Female", "Male"))
                     + "</div><input role=combobox aria-required=true aria-label='Country'>")
    fm = snapshot_form(page)
    radio = next(f for f in fm if f.kind == "radio_group")
    assert radio.required and radio.options == ["Female", "Male"]
    assert next(f for f in fm if f.label == "Country").required


def test_filler_refinds_a_field_whose_positional_id_shifted(page):
    from career_agent.browser.filler import _resync_sel

    # "State" appeared above, so the id the perceiver recorded for Sponsorship (#input-3) now belongs to State
    page.set_content("<input id=input-1 aria-label='Country'><input id=input-2 aria-label='State'>"
                     "<input id=input-3 aria-label='Will you now require sponsorship?'>")
    assert _resync_sel(page, "#input-3", "Will you now require sponsorship?") == "#input-3"
    assert page.locator(_resync_sel(page, "#input-2", "Will you now require sponsorship?")).get_attribute("id") == "input-3"


def test_flagged_invalid_field_is_retyped_and_chooser_button_uploads(page, tmp_path):
    from career_agent.browser.filler import apply_decisions, revalidate_invalid
    from career_agent.orchestrator.mapper import FillDecision

    pdf = tmp_path / "cv.pdf"; pdf.write_bytes(b"%PDF-1.4")
    page.set_content("<input id=a value='Rakshit' aria-invalid=true onblur=\"this.setAttribute('aria-invalid', this.value ? 'false' : 'true')\">"
                     "<button id=b onclick=\"const i=document.createElement('input');i.type='file';"
                     "i.onchange=()=>document.title=i.files[0].name;i.click()\">Select file</button>")
    assert revalidate_invalid(page) == 1 and page.get_attribute("#a", "aria-invalid") == "false"
    apply_decisions(page, [FillDecision("button:Select file", "button", "Select file", str(pdf), "upload_chooser", "resume")])
    assert page.title() == "cv.pdf"


def test_a_label_wrapping_a_select_is_the_question_not_the_option_list(page):
    from career_agent.browser.perception import snapshot_form

    page.set_content("<label>Source* <select id=s><option>Select</option><option>LinkedIn</option><option>Referral</option></select></label>")
    (f,) = [x for x in snapshot_form(page) if x.kind == "select"]
    assert f.label == "Source*" and f.options == ["LinkedIn", "Referral"]
