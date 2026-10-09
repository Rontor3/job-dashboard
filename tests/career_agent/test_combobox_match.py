from career_agent.memory.qbank_memory import QBankMemory
from career_agent.orchestrator.judgment import match_value_to_option


def test_a_recalled_combobox_answer_is_opened_and_picked_not_typed(qbank_conn, fake_embed, make_field):
    mem = QBankMemory(qbank_conn, embed=fake_embed)
    q = "Do you need visa sponsorship to work here?"
    fields = [make_field(q, kind=k, options=["Yes", "No"], ref="#" + k) for k in ("combobox", "select", "radio_group")]
    decisions, _ = mem.recall(fields)
    assert {d.ref: d.action for d in decisions} == {"#combobox": "combobox", "#select": "select",
                                                    "#radio_group": "check_group"}


def test_match_maps_synonym_via_llm():
    # value "Male" isn't in the list; the llm maps it to "Man".
    opts = ["Man", "Woman", "Non-binary"]
    for reply in ("Man", " man\n", "Answer: Man"):
        assert match_value_to_option("Gender", "Male", opts, lambda p: reply) == "Man", reply


def test_match_rejects_option_not_in_list():
    def llm(prompt): return "Helicopter"      # hallucinated -> reject
    assert match_value_to_option("Gender", "Male", ["Man", "Woman"], llm) is None


def test_an_ambiguous_reply_picks_nothing():
    # "man" is inside "woman": a reply naming both must not pick either
    assert match_value_to_option("Gender", "Male", ["Man", "Woman"], lambda p: "Man or Woman") is None


def test_a_none_reply_never_picks_a_none_option():
    opts = ["Asian", "White", "None"]
    assert match_value_to_option("Ethnicity", "Klingon", opts, lambda p: "NONE") is None
