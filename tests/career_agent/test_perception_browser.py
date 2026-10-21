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


def test_react_readonly_radios_and_aria_required_are_perceived():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form

    html = ("<div role=radiogroup><b>Gender</b>"
            + "".join(f"<input type=radio name=g value='{v}' readonly aria-required=true aria-label='{v}, Gender question'>" for v in ("Female", "Male"))
            + "</div><input role=combobox aria-required=true aria-label='Country'>")
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.set_content(html)
        fm = snapshot_form(page); b.close()
    radio = next(f for f in fm if f.kind == "radio_group")
    assert radio.required and radio.options == ["Female", "Male"]
    assert next(f for f in fm if f.label == "Country").required


def test_filler_refinds_a_field_whose_positional_id_shifted():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.filler import _resync_sel

    # "State" appeared above, so the id the perceiver recorded for Sponsorship (#input-3) now belongs to State
    html = ("<input id=input-1 aria-label='Country'><input id=input-2 aria-label='State'>"
            "<input id=input-3 aria-label='Will you now require sponsorship?'>")
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.set_content(html)
        assert _resync_sel(page, "#input-3", "Will you now require sponsorship?") == "#input-3"
        assert page.locator(_resync_sel(page, "#input-2", "Will you now require sponsorship?")).get_attribute("id") == "input-3"
        b.close()


def test_flagged_invalid_field_is_retyped_and_chooser_button_uploads(tmp_path):
    from playwright.sync_api import sync_playwright
    from career_agent.browser.filler import apply_decisions, revalidate_invalid
    from career_agent.orchestrator.mapper import FillDecision

    pdf = tmp_path / "cv.pdf"; pdf.write_bytes(b"%PDF-1.4")
    html = ("<input id=a value='Rakshit' aria-invalid=true onblur=\"this.setAttribute('aria-invalid', this.value ? 'false' : 'true')\">"
            "<button id=b onclick=\"const i=document.createElement('input');i.type='file';"
            "i.onchange=()=>document.title=i.files[0].name;i.click()\">Select file</button>")
    with sync_playwright() as pw:
        br = pw.chromium.launch(); page = br.new_page(); page.set_content(html)
        assert revalidate_invalid(page) == 1 and page.get_attribute("#a", "aria-invalid") == "false"
        apply_decisions(page, [FillDecision("button:Select file", "button", "Select file", str(pdf), "upload_chooser", "resume")])
        assert page.title() == "cv.pdf"
        br.close()


def test_a_label_wrapping_a_select_is_the_question_not_the_option_list():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form

    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page()
        page.set_content("<label>Source* <select id=s><option>Select</option><option>LinkedIn</option><option>Referral</option></select></label>")
        (f,) = [x for x in snapshot_form(page) if x.kind == "select"]
        assert f.label == "Source*" and f.options == ["LinkedIn", "Referral"]
        b.close()


def test_a_select_whose_question_sits_in_a_sibling_block_is_named_by_it_not_its_options():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form

    # Lever custom card (live JumpCloud form): the question is in .application-label, two levels above the select
    html = ('<ul><li class="application-question custom-question"><div>'
            '<div class="application-label full-width dropdown"><div class="text">I acknowledge that I may not record '
            'the interview.<span class="required">✱</span></div></div>'
            '<div class="application-field full-width required-field"><div class="application-dropdown">'
            '<select name="cards[46bf994f-a9a2][field0]" required><option value="">Select...</option>'
            '<option>Yes, I acknowledge this.</option><option>No, I do not acknowledge this.</option></select>'
            '</div></div></div></li></ul>')
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.set_content(html)
        (f,) = snapshot_form(page); b.close()
    assert f.label.startswith("I acknowledge that I may not record the interview.")
    assert f.options == ["Yes, I acknowledge this.", "No, I do not acknowledge this."]


def test_a_machine_named_textarea_takes_its_question_from_its_container_and_status_text_stays_out():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form

    # Lever card (job 30212): two custom textareas named cards[uuid][fieldN] share one li, each question a sibling
    # .application-label; a location typeahead carries a role=status "No location found" line beside its box.
    html = (Path(__file__).parent / "fixtures" / "lever_card_textareas.html").read_text()
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.set_content(html)
        by_name = {f.label.rstrip("*") for f in snapshot_form(page, scroll=False)}
        fields = {f.kind + ":" + f.ref: f for f in snapshot_form(page, scroll=False)}
        b.close()
    assert not any(l.startswith("cards[") for l in by_name), by_name
    assert "Which harnesses do you have experience building with? Please name the harness." in by_name
    assert "What is your experience with fine-tuning or adapting LLMs?" in by_name
    loc = [f for f in fields.values() if f.kind == "combobox"]
    assert loc and loc[0].label.startswith("Current location")
    assert "No location found" not in loc[0].label and "Loading" not in loc[0].label


def test_a_visibility_hidden_or_transparent_button_is_not_a_control_on_screen():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form

    # Avature keeps a "Default Apply" button in the DOM with visibility:hidden / opacity:0; only the visible Apply counts.
    html = ('<button style="visibility:hidden">Default Apply</button>'
            '<button style="opacity:0">Ghost Apply</button>'
            '<button>Apply now</button>')
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.set_content(html)
        labels = [f.label for f in snapshot_form(page, scroll=False) if f.kind == "button"]
        b.close()
    assert labels == ["Apply now"], labels
