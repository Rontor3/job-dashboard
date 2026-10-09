"""Which child frames the field reader (perception.collect_raw) looks into.

Rule: skip known non-application services by address, skip hidden/small frames,
wait briefly for a frame to load, then keep a frame only if it holds real form
fields. Known ATS hosts are trusted (no size / field checks, longer load wait)."""
import pytest

from career_agent.browser.perception import (
    ATS_FRAME_HOSTS, is_denied_frame, is_trusted_frame, looks_like_application,
)


def _row(kind, label, ref="#x"):
    return {"kind": kind, "label": label, "ref": ref}


@pytest.mark.parametrize("url", [
    "https://www.google.com/recaptcha/api2/anchor?k=1", "https://www.gstatic.com/recaptcha/releases/x/",
    "https://newassets.hcaptcha.com/captcha/v1/", "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/",
    "https://client-api.arkoselabs.com/v2/", "https://gt4.geetest.com/", "https://www.googletagmanager.com/ns.html",
    "https://stats.g.doubleclick.net/", "https://tpc.googlesyndication.com/", "https://widget.intercom.io/widget/x",
    "https://js.driftt.com/", "https://static.zdassets.com/", "https://www.youtube.com/embed/abc",
    "about:blank", "",
])
def test_known_non_application_frames_are_denied(url):
    assert is_denied_frame(url), url


@pytest.mark.parametrize("url", [
    "https://boards.greenhouse.io/embed/job_app?for=acme", "https://swiggy.mynexthire.com/employer/jobs",
    "https://careers.acme.com/apply/embed", "about:srcdoc", "https://acme.zohorecruit.com/forms/abc",
])
def test_everything_else_may_be_an_application(url):
    assert not is_denied_frame(url), url


def test_listed_ats_hosts_are_trusted_and_the_lists_do_not_overlap():
    assert is_trusted_frame("https://boards.greenhouse.io/embed/job_app")
    assert not is_trusted_frame("https://swiggy.mynexthire.com/x")
    assert not any(is_denied_frame("https://" + h + "/") for h in ATS_FRAME_HOSTS)


def test_two_real_fields_make_an_application():
    assert looks_like_application([_row("text", "First name"), _row("email", "Email Address"), _row("button", "Apply")])


def test_one_field_plus_a_button_is_enough_for_a_first_step():
    assert looks_like_application([_row("email", "Email"), _row("button", "Continue")])


def test_one_field_alone_or_a_button_alone_is_not():
    assert not looks_like_application([_row("text", "Search jobs")])
    assert not looks_like_application([_row("button", "Apply")])
    assert not looks_like_application([])


def test_a_captcha_frame_has_no_real_fields():
    assert not looks_like_application([
        _row("checkbox", "I'm not a robot"), _row("textarea", "", "#g-recaptcha-response"),
        _row("text", "", "#h-captcha-response"), _row("button", "Verify")])


def test_choice_only_frames_do_not_count():
    assert not looks_like_application([_row("checkbox", "Accept cookies"), _row("radio", "Decline"),
                                       _row("button", "Save")])


def test_fields_without_a_label_do_not_count():
    assert not looks_like_application([_row("text", ""), _row("text", "  "), _row("button", "Go")])
