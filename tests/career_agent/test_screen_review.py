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


def test_unresolvable_prose_purpose_goes_to_judgment_not_dropped():
    from types import SimpleNamespace as NS
    from career_agent.browser.form_model import Field, guess_purpose
    from career_agent.orchestrator.screen_review import map_screen
    label = "Start a conversation with the team at HUD. Share something about you, or why HUD interests you."
    assert guess_purpose(label, "textarea") == "motivation"
    f = Field("#m", "textarea", label, False, [], None, "motivation")
    decisions, needs = map_screen([f], NS(contact={}, experiences=[], education=[], summary=None))
    assert decisions == [] and [x.ref for x in needs] == ["#m"]


def test_optional_single_line_field_without_answer_is_left_blank():
    opt = _f("#alt", "Alternate Number", None)
    req = _f("#req", "Something odd *", None, required=True)
    essay = _f("#es", "Anything else?", None, kind="textarea")
    _, needs = map_screen([opt, req, essay], P)
    assert [f.ref for f in needs] == ["#req", "#es"]


def test_if_yes_followup_has_no_profile_purpose():
    from career_agent.browser.form_model import guess_purpose
    assert guess_purpose("If yes, please indicate your family member's name, job title and work location", "text") is None


def test_i_have_read_the_privacy_notice_is_an_attestation():
    from career_agent.browser.form_model import guess_purpose
    assert guess_purpose("I have read the KHC Privacy Notice.", "checkbox") == "attestation"


def test_ctc_is_written_in_the_unit_the_box_wants():
    from career_agent.orchestrator.answering import normalize_amount as n
    assert n("30 LPA", "Annual Base Salary Expectations (local currency)") == "3000000"
    assert n("25", "Current CTC in INR (annual, digits only)") == "2500000"
    assert n("25", "Current CTC (LPA)") == "25" and n("35 LPA", "Expected salary in lakhs per annum") == "35"
    assert n("35 LPA", "Salary expectation per month") == "291667"
    assert n("25", "Current CTC") == "25 LPA" and n("25", "Current CTC", "number") == "2500000"
    assert n("35 LPA", "Expected CTC") == "35 LPA"
    assert n("2500000", "Current CTC (INR)") == "2500000"
    assert n("30 LPA", "Preferred location") == "30 LPA"


def test_what_you_earn_now_is_not_what_you_expect():
    from career_agent.browser.form_model import guess_purpose as g
    assert g("What’s your current salary? (in lakhs per annum)", "text") == "current_ctc"
    assert g("Last drawn salary", "text") == "current_ctc" and g("Current / Last compensation - Amount", "text") == "current_ctc"
    assert g("Expected salary", "text") == "salary_expectation" and g("Annual Base Salary Expectations (local currency)", "text") == "salary_expectation"


def test_a_rerun_reuses_what_the_human_already_answered_for_that_job(tmp_path):
    import sqlite3
    from job_dashboard import qa_store
    from career_agent.orchestrator.answering import answer_fields
    from career_agent.orchestrator.qa_recorder import QARecorder

    conn = sqlite3.connect(tmp_path / "x.db"); qa_store.ensure(conn)
    qa_store.record(conn, job_id=7, run_key="old", ref="#a", label="Source*", answer="LinkedIn", source="human", status="answered")
    qa_store.record(conn, job_id=7, run_key="old", ref="#b", label="I want to be considered for other job opportunities", answer="yes", source="human", status="answered")
    qa_store.record(conn, job_id=8, run_key="other", ref="#a", label="Source*", answer="Naukri", source="human", status="answered")   # another job
    fields = [_f("#s", "Source*", None, kind="select"), _f("#c", "I want to be considered for other job opportunities", None, kind="checkbox"),
              _f("#n", "Anything else", None)]
    ctx = {"profile": P, "qa": QARecorder(conn, 7, run_key="new")}
    decisions, needs = answer_fields(fields, ctx)
    by = {d.label: d for d in decisions if d.source == "human_prior"}
    assert by["Source*"].value == "LinkedIn" and by["Source*"].action == "select"
    assert by["I want to be considered for other job opportunities"].action == "check"
    assert "#n" not in {d.ref for d in decisions}                       # nothing known about it: not invented
