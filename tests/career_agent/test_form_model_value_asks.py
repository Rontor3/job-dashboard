"""Labels that ask one value or a place, not prose and not a résumé name (Fractal, live 2026-10-31)."""
from career_agent.browser.form_model import asks_for_value, guess_purpose
from career_agent.orchestrator.claude_assist import error_shaped


def test_identifier_label_asks_for_a_value_and_a_refusal_is_not_an_answer():
    assert asks_for_value("Enter the Roll number/ Seat Number / Registration Number of your Highest Education")
    assert not asks_for_value("Tell us about a project you are proud of")
    assert error_shaped("I do not have access to my personal registration or seat number in this context.")


def test_which_country_of_the_institution_is_a_place_not_the_school():
    q = "The Institution where you completed your highest education qualification is located in which Country?"
    assert guess_purpose(q, "combobox") != "school"
    assert guess_purpose("Institution", "text") == "school"
