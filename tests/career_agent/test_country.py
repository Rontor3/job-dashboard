from career_agent.browser.form_model import guess_purpose
from career_agent.memory.candidate_profile import CandidateProfile
from career_agent.orchestrator.profile_resolver import resolve


def test_country_purpose_and_resolution():
    assert guess_purpose("Country*", "text") == "country"
    p = CandidateProfile(contact={"location": "Mumbai, India"})
    assert resolve("country", p) == "India"


def test_country_without_comma_escalates():
    p = CandidateProfile(contact={"location": "Remote"})
    assert resolve("country", p) is None  # can't determine a country
