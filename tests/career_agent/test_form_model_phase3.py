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
