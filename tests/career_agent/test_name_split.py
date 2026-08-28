from career_agent.browser.form_model import guess_purpose
from career_agent.memory.candidate_profile import CandidateProfile
from career_agent.orchestrator.profile_resolver import resolve


def test_first_last_purposes_beat_full_name():
    assert guess_purpose("First Name*", "text") == "first_name"
    assert guess_purpose("Given name", "text") == "first_name"
    assert guess_purpose("Last Name", "text") == "last_name"
    assert guess_purpose("Surname", "text") == "last_name"
    assert guess_purpose("Family Name", "text") == "last_name"
    assert guess_purpose("Full Name", "text") == "full_name"  # unchanged


def test_resolve_splits_full_name():
    p = CandidateProfile(contact={"full_name": "Rakshit Singh"})
    assert resolve("first_name", p) == "Rakshit"
    assert resolve("last_name", p) == "Singh"


def test_resolve_prefers_explicit_contact_names():
    p = CandidateProfile(contact={"full_name": "A B C", "first_name": "A", "last_name": "C"})
    assert resolve("first_name", p) == "A"
    assert resolve("last_name", p) == "C"


def test_single_token_name_has_empty_last():
    p = CandidateProfile(contact={"full_name": "Prince"})
    assert resolve("first_name", p) == "Prince"
    assert resolve("last_name", p) is None
