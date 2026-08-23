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


def test_unknown_or_missing_becomes_review():
    form = [_f("#x", "text", "Favourite colour?", None),
            _f("#s", "text", "Expected salary", "salary_expectation")]  # not in PROFILE
    decisions = {d.ref: d for d in map_fields(form, PROFILE, None)}
    assert decisions["#x"].action == "review" and decisions["#x"].value is None
    assert decisions["#s"].action == "review"


def test_radio_group_uses_check_group_action():
    form = [_f("group:auth", "radio_group", "authorized", "work_authorization",
               options=["Yes", "No"])]
    d = map_fields(form, PROFILE, None)[0]
    assert d.action == "check_group"
    assert d.value == "US Citizen"
