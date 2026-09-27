from career_agent.memory.candidate_profile import CandidateProfile, Experience, Education
from career_agent.orchestrator.profile_resolver import resolve

P = CandidateProfile(
    contact={"full_name": "Rakshit", "email": "r@x.com"},
    experiences=[Experience("Tata AIG", "Data Scientist", "July 2023", "Present", ["b"]),
                 Experience("OYO", "Intern", "May 2022", "Jul 2022", [])],
    education=[Education("IIT", "B.Tech", "CS", "2018", "2022")],
    skills=["Python", "SQL"])

def test_scalar_and_indexed_resolution():
    assert resolve("full_name", P) == "Rakshit"
    assert resolve("employer", P, 0) == "Tata AIG"
    assert resolve("job_title", P, 0) == "Data Scientist"
    assert resolve("employer", P, 1) == "OYO"
    assert resolve("school", P, 0) == "IIT"
    assert resolve("degree", P, 0) == "B.Tech"
    assert resolve("field_of_study", P, 0) == "CS"
    assert resolve("skills", P) == "Python, SQL"

def test_missing_returns_none():
    assert resolve("employer", P, 5) is None
    assert resolve("gpa", P, 0) is None

def test_graduation_year_extracted_from_education_end():
    assert resolve("graduation_year", P, 0) == "2022"
    no_dates = CandidateProfile(education=[Education("IIT", "B.Tech")])
    assert resolve("graduation_year", no_dates, 0) is None    # escalate, don't guess

def test_phone_strips_country_code_prefix():
    p = CandidateProfile(contact={"phone": "+91 7565052330"})
    assert resolve("phone", p) == "7565052330"

def test_phone_without_country_code_unchanged():
    p = CandidateProfile(contact={"phone": "7565052330"})
    assert resolve("phone", p) == "7565052330"

def test_phone_extension_never_guessed_from_phone_number():
    # extension has no dedicated profile field — must never reuse the phone value
    assert resolve("phone_extension", P) is None


def test_phone_country_code_label_and_value():
    from types import SimpleNamespace as NS
    from career_agent.browser.form_model import guess_purpose
    from career_agent.orchestrator.profile_resolver import resolve
    for label in ("Phone country code*", "Country code", "Dialing code", "Country calling code"):
        assert guess_purpose(label, "select") == "phone_country_code", label
    assert guess_purpose("Mobile phone number*", "tel") == "phone"
    p = NS(contact={"phone": "+91 7565052330"})
    assert resolve("phone_country_code", p) == "+91"
    assert resolve("phone_country_code", NS(contact={"phone": "7565052330"})) is None
