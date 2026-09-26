from career_agent.browser.form_model import Field
from career_agent.memory.candidate_profile import CandidateProfile, Experience
from career_agent.orchestrator.screen_review import map_screen, apply_answers

P = CandidateProfile(contact={"full_name": "Rakshit", "email": "r@x.com"},
                     experiences=[Experience("Tata AIG", "Data Scientist", "2023", "Present", [])],
                     skills=["Python"])

def _f(ref, label, purpose, required=False, kind="text"):
    return Field(ref, kind, label, required, [], None, purpose)

def test_fills_known_and_flags_unknown():
    form = [_f("#n", "Full name", "full_name"),
            _f("#emp", "Employer", "employer"),
            _f("#q", "Why do you want this job?", None, required=True, kind="textarea"),
            _f("#missing", "Portfolio URL", "portfolio_url", required=True)]
    decisions, needs = map_screen(form, P)
    d = {x.ref: x for x in decisions}
    assert d["#n"].value == "Rakshit" and d["#emp"].value == "Tata AIG"
    refs = {f.ref for f in needs}
    assert "#q" in refs          # novel required question -> human
    assert "#missing" in refs    # required, no profile value -> human

def test_apply_answers():
    needs = [_f("#q", "Why?", None, required=True, kind="textarea")]
    decisions = apply_answers(needs, {"#q": "Because I love ML."})
    assert decisions[0].value == "Because I love ML." and decisions[0].action == "fill"


def _sel(ref, label, purpose, options, required=True):
    return Field(ref, "select", label, required, options, None, purpose)


def test_option_coercion_and_escalation():
    P = CandidateProfile(contact={})
    yn = ["Yes", "No"]
    spons = _sel("#sp", "Will you require visa sponsorship?", "visa_sponsorship", yn)
    auth_us = _sel("#au", "Authorized to work in the US?", "work_authorization", yn)
    auth_none = _sel("#an", "Are you authorized to work?", "work_authorization", yn)
    no_opt = _sel("#x", "Will you require sponsorship?", "visa_sponsorship", ["Maybe", "Later"])
    decisions, needs = map_screen([spons, auth_us, auth_none, no_opt], P)
    d = {x.ref: x for x in decisions}
    assert d["#sp"].value == "Yes"
    assert d["#au"].value == "No"
    assert "#an" in {f.ref for f in needs}    # no country -> escalate
    assert "#x" in {f.ref for f in needs}     # no matching option -> escalate


def test_boolean_value_normalized_to_yes_no():
    P = CandidateProfile(contact={"willing_to_relocate": True})
    f = _sel("#r", "Willing to relocate?", "willing_to_relocate", ["Yes", "No"])
    decisions, needs = map_screen([f], P)
    assert {x.ref: x for x in decisions}["#r"].value == "Yes"


def test_no_prefers_exact_over_na_option():
    # M-1: answer "No" must pick "No", not "N/A"
    P = CandidateProfile(contact={})
    f = _sel("#c", "Prior contact at company?", "prior_contact", ["N/A", "No"])
    decisions, needs = map_screen([f], P)
    assert {x.ref: x for x in decisions}["#c"].value == "No"


def test_required_attestation_ticked_optional_left():
    P = CandidateProfile(contact={})
    tc = Field("#tc", "checkbox", "I agree with the terms and conditions", True, [], None, "attestation")
    mkt = Field("#mk", "checkbox", "I agree to receive marketing communications", False, [], None, "attestation")
    decisions, needs = map_screen([tc, mkt], P)
    d = {x.ref: x for x in decisions}
    assert d["#tc"].action == "check" and d["#tc"].value is True   # required T&C -> ticked (draft)
    assert d["#mk"].action == "attestation"                        # optional marketing -> not ticked


def test_non_resume_file_field_escalates():
    # I-3: a cover-letter upload must NOT receive the résumé PDF
    P = CandidateProfile(contact={})
    cv = Field("#cv", "file", "Attach resume", False, [], None, "resume_upload")
    cover = Field("#cl", "file", "Cover Letter", False, [], None, None)
    decisions, needs = map_screen([cv, cover], P, resume_pdf="/tmp/cv.pdf")
    d = {x.ref: x for x in decisions}
    assert d["#cv"].value == "/tmp/cv.pdf" and d["#cv"].action == "upload"
    assert "#cl" in {f.ref for f in needs}   # cover letter -> escalate, no résumé
