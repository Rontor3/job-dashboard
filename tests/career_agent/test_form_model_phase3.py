from career_agent.browser.form_model import guess_purpose, KNOWN_PURPOSES


def test_experience_and_education_purposes():
    assert guess_purpose("Employer", "text") == "employer"
    assert guess_purpose("Company Name", "text") == "employer"
    assert guess_purpose("Job Title", "text") == "job_title"
    assert guess_purpose("Start Date", "text") == "start_date"
    assert guess_purpose("End Date", "text") == "end_date"
    assert guess_purpose("University / School", "text") == "school"
    assert guess_purpose("Degree", "text") == "degree"
    assert guess_purpose("Field of Study", "text") == "field_of_study"
    assert guess_purpose("Key Skills", "textarea") == "skills"


def test_new_purposes_are_known():
    for lbl, kind in [("Employer", "text"), ("Degree", "text"), ("Key Skills", "textarea")]:
        assert guess_purpose(lbl, kind) in KNOWN_PURPOSES


def test_middle_name_variants_all_map_to_middle_name():
    from career_agent.browser.form_model import guess_purpose
    for label in ["Middle Name", "Middle", "Middle Initial", "Middle Name(s)"]:
        assert guess_purpose(label, "text") == "middle_name", label
    # full-name / first-name still unaffected
    assert guess_purpose("Full Name", "text") == "full_name"
    assert guess_purpose("First Name", "text") == "first_name"


def test_address_question_is_not_mistagged_as_relocate():
    from career_agent.browser.form_model import guess_purpose
    # the exact Oracle field that got "Yes": it mentions relocate but IS an address box
    label = ("What is the address from which you plan on working? "
             "If you would need to relocate, please type \"relocating\".")
    assert guess_purpose(label, "text") == "address"          # not willing_to_relocate
    # a real willingness question still maps to relocate
    assert guess_purpose("Are you willing to relocate?", "select") == "willing_to_relocate"
    # "Email Address" must still be email, not address
    assert guess_purpose("Email Address", "text") == "email"


def test_address_purpose_escalates_when_no_value():
    from career_agent.browser.form_model import Field
    from career_agent.memory.candidate_profile import CandidateProfile
    from career_agent.orchestrator.screen_review import map_screen
    f = Field("#addr", "text", "Home address", True, [], None, "address")
    decisions, needs = map_screen([f], CandidateProfile(contact={}))
    assert "#addr" in {x.ref for x in needs}               # escalated, not filled with junk


def test_checkbox_never_gets_a_text_value_purpose():
    from career_agent.browser.form_model import guess_purpose
    # a checkbox can't hold a typed name/email/phone -> those purposes are dropped
    assert guess_purpose("Use name only", "checkbox") is None
    assert guess_purpose("Email me updates", "checkbox") is None
    # attestation checkboxes still resolve
    assert guess_purpose("I agree to the terms and conditions", "checkbox") == "attestation"
    # a yes/no QUESTION rendered as a checkbox keeps its question purpose
    assert guess_purpose("Do you require visa sponsorship?", "checkbox") == "visa_sponsorship"
    # a plain text name field is unaffected
    assert guess_purpose("Full Name", "text") == "full_name"
