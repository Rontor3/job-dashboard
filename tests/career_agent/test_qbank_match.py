from career_agent.memory.qbank_match import (CONFIDENT, LIKELY, NONE, answer_field, is_junk,
                                             llm_pick, match_question, split_escape)

RELOC = ('What is the address from which you plan on working? '
         'If you would need to relocate, please type "relocating".')


def test_split_escape():
    assert split_escape(RELOC) == ("What is the address from which you plan on working?", "relocating")
    assert split_escape("Middle name", 'Enter "N/A" if none') == ("Middle name", "N/A")
    assert split_escape("Street address") == ("Street address", None)


def test_junk_labels(make_field):
    assert is_junk(make_field("yes")) and is_junk(make_field("cards[184c][field3]"))
    assert is_junk(make_field("")) and is_junk(make_field("Male", "radio_group", ["Male", "Female"]))
    assert not is_junk(make_field("Gender")) and not is_junk(make_field("Veteran Status"))


def test_exact_wording_is_confident(qbank_conn, fake_embed):
    m = match_question(qbank_conn, "Notice period?", embed=fake_embed)
    assert (m.band, m.entry_id, m.kind, m.score) == (CONFIDENT, "notice_period", "exact", 1.0)


def test_unrelated_question_is_none_but_logs_candidates(qbank_conn, fake_embed):
    m = match_question(qbank_conn, "Describe your favourite hobby outside work", embed=fake_embed)
    assert m.band == NONE and m.entry_id is None and m.candidates


def test_ambiguous_goes_to_llm_which_may_say_none(qbank_conn, fake_embed):
    prompts = []
    m = match_question(qbank_conn, "Do you need sponsorship for a visa?", embed=fake_embed,
                       llm=lambda p: prompts.append(p) or "NONE", high=0.99)
    assert prompts and (m.band, m.kind, m.entry_id) == (NONE, "llm", None)


def test_llm_pick_marks_likely(qbank_conn, fake_embed):
    m = match_question(qbank_conn, "Do you need sponsorship for a visa?", embed=fake_embed,
                       llm=lambda p: "a", high=0.99)
    assert (m.band, m.entry_id) == (LIKELY, "sponsorship_required")


def test_llm_pick_is_validated(qbank_conn):
    ids = ["race", "hispanic_latino"]
    assert llm_pick("q", ids, qbank_conn, lambda p: "(b)") == "hispanic_latino"
    assert llm_pick("q", ids, qbank_conn, lambda p: "<think>hmm</think>a") == "race"
    assert llm_pick("q", ids, qbank_conn, lambda p: "Asian") is None      # a value, not a letter
    assert llm_pick("q", ids, qbank_conn, lambda p: "c") is None          # out of range
    assert llm_pick("q", ids, qbank_conn, None) is None


def test_polarity_difference_caps_at_likely(qbank_conn, fake_embed):
    m = match_question(qbank_conn, "Will you not require visa sponsorship?", embed=fake_embed, high=0.5)
    assert (m.entry_id, m.band) == ("sponsorship_required", LIKELY) and "polarity" in m.note


def test_relocating_flow(qbank_conn, fake_embed, make_field):
    f = make_field(RELOC)
    m, v = answer_field(qbank_conn, f, embed=fake_embed, job={"location": "San Francisco, CA"})
    assert (m.band, m.entry_id, m.escape, v) == (CONFIDENT, "work_location", "relocating", "relocating")
    _, v = answer_field(qbank_conn, f, embed=fake_embed, job={"location": "Noida, India"})
    assert v == "C-12, Sector 5, Noida 201301"


def test_profile_ref_and_unanswered(qbank_conn, fake_embed, make_field):
    m, v = answer_field(qbank_conn, make_field("Race"), embed=fake_embed, contact={"ethnicity": "Asian"})
    assert (m.entry_id, v) == ("race", "Asian")
    m, v = answer_field(qbank_conn, make_field("Race"), embed=fake_embed, contact={})
    assert (m.band, v, m.note) == (NONE, None, "no answer for entry")


def test_shape_failure_caps_at_likely(qbank_conn, fake_embed, make_field):
    m, v = answer_field(qbank_conn, make_field("LinkedIn profile URL"), embed=fake_embed)
    assert (m.band, v) == (LIKELY, "linkedin.com/in/x") and "shape url" in m.note


def test_option_fit(qbank_conn, fake_embed, make_field):
    f = make_field("Will you require visa sponsorship?", "select",
                   ["I will require sponsorship", "I do not require sponsorship"])
    assert answer_field(qbank_conn, f, embed=fake_embed)[1] == "I will require sponsorship"
    f = make_field("Are you Hispanic or Latino?", "radio_group", ["Yes", "No", "Decline"])
    assert answer_field(qbank_conn, f, embed=fake_embed)[1] == "No"
    f = make_field("Will you require visa sponsorship?", "select", ["Option A", "Option B"])
    m, v = answer_field(qbank_conn, f, embed=fake_embed)         # nothing fits, no LLM -> flag
    assert (m.band, v) == (NONE, None)


def test_non_bank_fields_skipped(qbank_conn, fake_embed, make_field):
    assert answer_field(qbank_conn, make_field("Resume", "file"), embed=fake_embed)[0].note == "not a bank field"
    assert answer_field(qbank_conn, make_field("yes"), embed=fake_embed)[0].note == "junk label"


def test_page_declared_input_type_drives_shape(qbank_conn, fake_embed, make_field):
    m, v = answer_field(qbank_conn, make_field("Notice period", input_type="email"), embed=fake_embed)
    assert (m.band, v) == (LIKELY, "30") and "shape email" in m.note
    m, _ = answer_field(qbank_conn, make_field("Notice period", input_type="number"), embed=fake_embed)
    assert m.band == CONFIDENT
