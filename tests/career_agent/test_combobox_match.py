from career_agent.orchestrator.mapper import _action_for_kind
from career_agent.orchestrator.judgment import match_value_to_option


def test_action_for_combobox():
    assert _action_for_kind("combobox") == "combobox"


def test_match_maps_synonym_via_llm():
    # value "Male" isn't in the list; the llm maps it to "Man".
    def llm(prompt): return "Man"
    assert match_value_to_option("Gender", "Male", ["Man", "Woman", "Non-binary"], llm) == "Man"


def test_match_rejects_option_not_in_list():
    def llm(prompt): return "Helicopter"      # hallucinated -> reject
    assert match_value_to_option("Gender", "Male", ["Man", "Woman"], llm) is None


def test_match_handles_none_reply():
    def llm(prompt): return "NONE"
    assert match_value_to_option("Ethnicity", "Klingon", ["Asian", "White"], llm) is None
