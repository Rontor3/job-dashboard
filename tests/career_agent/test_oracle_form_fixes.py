from career_agent.browser.form_model import Field, guess_purpose
from career_agent.memory.candidate_profile import CandidateProfile
from career_agent.orchestrator.profile_resolver import resolve
from career_agent.orchestrator.advance import pick_advance_label, has_control, ADVANCE_NAMES


def test_middle_name_does_not_get_full_name():
    assert guess_purpose("Middle Name", "text") == "middle_name"
    # no middle name in the profile -> resolves to None (escalate/blank), NOT the full name
    p = CandidateProfile(contact={"full_name": "Rakshit Singh"})
    assert resolve("middle_name", p) is None


def test_city_resolves_to_city_part_not_whole_location():
    assert guess_purpose("City *", "text") == "city"
    p = CandidateProfile(contact={"location": "Mumbai, India"})
    assert resolve("city", p) == "Mumbai"
    assert resolve("country", p) == "India"


def test_armed_forces_is_not_classified_as_country():
    label = "Have you ever served as a member of the armed forces of any country?"
    assert guess_purpose(label, "text") == "veteran"
    # veteran is not auto-answered -> resolves to None
    assert resolve("veteran", CandidateProfile(contact={"location": "Mumbai, India"})) is None


def test_address_line_no_longer_grabs_location():
    # "Address Line 1" -> `address` purpose, which escalates (no street address in
    # profile) rather than auto-filling the bare location string.
    assert guess_purpose("Address Line 1", "text") == "address"
    assert resolve("address", CandidateProfile(contact={"location": "Mumbai, India"})) is None


def test_advance_ignores_session_dialog_buttons():
    form = [Field("#a", "button", "Continue Working", False, [], None, None),
            Field("#b", "button", "End Session", False, [], None, None),
            Field("#c", "button", "Save and Continue", False, [], None, None)]
    assert pick_advance_label(form, is_last=False) == "Save and Continue"
    only_session = [Field("#a", "button", "Continue Working", False, [], None, None)]
    assert has_control(only_session, ADVANCE_NAMES) is False
