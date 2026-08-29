from career_agent.browser.form_model import guess_purpose
from career_agent.memory.candidate_profile import CandidateProfile
from career_agent.orchestrator.profile_resolver import resolve


def test_demographic_purposes():
    assert guess_purpose("Gender", "select") == "gender"
    assert guess_purpose("Race / Ethnicity", "select") == "ethnicity"
    assert guess_purpose("Are you Hispanic or Latino?", "select") == "ethnicity"
    assert guess_purpose("Disability Status", "select") == "disability"
    assert guess_purpose("Have you served in the armed forces?", "select") == "veteran"


def test_resolve_demographics_from_contact():
    p = CandidateProfile(contact={"gender": "Male", "ethnicity": "Asian",
                                  "veteran_status": "No", "disability_status": "No"})
    assert resolve("gender", p) == "Male"
    assert resolve("ethnicity", p) == "Asian"
    assert resolve("veteran", p) == "No"
    assert resolve("disability", p) == "No"
    # absent -> None (escalate), never a guess
    assert resolve("gender", CandidateProfile(contact={})) is None
