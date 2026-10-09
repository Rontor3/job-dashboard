from career_agent.browser.form_model import guess_purpose


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


def test_job_title_bare_word_only_matches_as_a_short_label():
    # bare field name -> job_title (common on simpler ATSs)
    assert guess_purpose("Position", "text") == "job_title"
    assert guess_purpose("Position*", "text") == "job_title"
    assert guess_purpose("Title", "text") == "job_title"
    assert guess_purpose("Position Title", "text") == "job_title"
    # the same word embedded in a real question -> must NOT be job_title
    assert guess_purpose(
        "What is the approximate timeline for beginning a new position with us?",
        "textarea") != "job_title"


def test_bare_name_and_qualification_only_match_as_a_short_label():
    assert guess_purpose("Name", "text") == "full_name"
    assert guess_purpose(
        "Does the Legal Name you provided match the name on your legal ID?",
        "select") != "full_name"
    assert guess_purpose(
        "Do you certify you meet all minimum qualifications for this job "
        "as outlined in the job posting?", "select") != "degree"


def test_bare_employer_and_mobile_only_match_as_a_short_label():
    assert guess_purpose("Employer", "text") == "employer"
    assert guess_purpose("Mobile", "tel") == "phone"
    assert guess_purpose(
        "Have you signed a non-compete agreement with your current or "
        "previous employer and/or any other agreement which might "
        "restrict your employment?", "select") != "employer"
    assert guess_purpose(
        "Would you like to receive mobile text message updates from us "
        "regarding the recruiting process?", "select") != "phone"


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
