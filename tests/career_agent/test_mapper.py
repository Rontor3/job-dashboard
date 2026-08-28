from career_agent.browser.form_model import Field
from career_agent.orchestrator.mapper import map_fields, FillDecision

PROFILE = {
    "full_name": "Test User", "email": "t@example.com", "phone": "+1-555-0100",
    "linkedin_url": "https://linkedin.com/in/test", "work_authorization": "US Citizen",
    "notice_period": "2 weeks",
}


def _f(ref, kind, label, purpose, options=None):
    return Field(ref=ref, kind=kind, label=label, required=False,
                 options=options or [], group=None, purpose=purpose)


def test_direct_profile_fields_fill_from_profile():
    form = [_f("#n", "text", "Full name", "full_name"),
            _f("#e", "email", "Email", "email")]
    decisions = {d.ref: d for d in map_fields(form, PROFILE, None)}
    assert decisions["#n"].value == "Test User"
    assert decisions["#n"].action == "fill"
    assert decisions["#n"].source == "profile"
    assert decisions["#e"].value == "t@example.com"


def test_attestation_is_never_auto_valued():
    form = [_f("#c", "checkbox", "I certify this is true", "attestation")]
    d = map_fields(form, PROFILE, None)[0]
    assert d.action == "attestation"
    assert d.value is None


def test_resume_upload_uses_resume_path():
    form = [_f("#r", "file", "Upload resume", "resume_upload")]
    d = map_fields(form, PROFILE, "/tmp/cv.pdf")[0]
    assert d.action == "upload" and d.value == "/tmp/cv.pdf"


def test_resume_upload_without_path_becomes_review():
    form = [_f("#r", "file", "Upload resume", "resume_upload")]
    d = map_fields(form, PROFILE, None)[0]
    assert d.action == "review" and d.value is None


def test_unknown_or_missing_becomes_review():
    form = [_f("#x", "text", "Favourite colour?", None),
            _f("#s", "text", "Expected salary", "salary_expectation")]  # not in PROFILE
    decisions = {d.ref: d for d in map_fields(form, PROFILE, None)}
    assert decisions["#x"].action == "review" and decisions["#x"].value is None
    assert decisions["#s"].action == "review"


def test_buttons_are_not_review_items():
    # Perception now captures nav/submit buttons so the step engine can find
    # them; the Phase-1 card must ignore them (not fillable, not "needs input").
    form = [_f("#n", "text", "Full name", "full_name"),
            _f("button:Continue", "button", "Continue", None),
            _f("button:Submit", "button", "Submit application", None)]
    decisions = map_fields(form, PROFILE, None)
    assert {d.ref for d in decisions} == {"#n"}


def test_radio_group_checks_when_value_is_an_option():
    # profile value literally matches one of the options -> auto check.
    form = [_f("group:auth", "radio_group", "authorized", "work_authorization",
               options=["US Citizen", "Not authorized"])]
    d = map_fields(form, PROFILE, None)[0]
    assert d.action == "check_group"
    assert d.value == "US Citizen"


def test_option_field_value_not_in_options_becomes_review():
    # "US Citizen" is not a Yes/No option -> deciding the mapping is judgment,
    # so it must fall to human review, never a blind (hanging) click.
    radio = _f("group:auth", "radio_group", "authorized", "work_authorization",
               options=["Yes", "No"])
    select = _f("#auth2", "select", "Work authorization", "work_authorization",
                options=["Yes", "No"])
    decisions = map_fields([radio, select], PROFILE, None)
    assert all(d.action == "review" and d.value is None for d in decisions)
