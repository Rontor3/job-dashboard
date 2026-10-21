"""The vocabulary bridge (fit_option rung 2) and the typed-fill shape gate for
empty-options fields — the 30901 class: the bank had '+91' and 'Job Board', the
site said 'India (+91)' or loaded its options after the answer was written, and
the raw value was typed and died. The golden pairs the triage replayed live:
docs/career-agent/triage/answer-pipeline-analysis.md §2.1."""
from career_agent.memory.qbank import add_wording, set_answer, upsert_entry
from career_agent.memory.qbank_match import (CONFIDENT, LIKELY, NONE, answer_field,
                                             bridge_option, fit_option, vocab_norm)
from career_agent.memory.qbank_rules import dial_label, infer_shape


DIAL_LIST = ["🇦🇬 (+1 268) Antigua and Barbuda", "🇮🇳 (+91) India", "🇮🇹 (+39) Italy", "+91 (India)", "+1 (United States)"]


def _seed(conn, embed, eid, question, answer, synonyms=None):
    """A bank entry the way seed/curate write one; wordings linked for exact hits."""
    upsert_entry(conn, {"id": eid, "question": question, "topic": "misc", "atype": "text",
                        "synonyms": synonyms or {}})
    set_answer(conn, eid, answer)
    add_wording(conn, question, eid, embed([question])[0], "seed")


# ── rung 2: the vocabulary bridge ────────────────────────────────────────────

def test_vocab_norm_keeps_the_plus_and_digits_whole():
    assert vocab_norm("India (+91)") == "india +91"
    assert vocab_norm("🇮🇳 (+91) India") == "+91 india"
    assert vocab_norm("Job Board - Other") == "job board other"
    assert vocab_norm("+ 91") == "+91"                    # a plus never drifts off its code


def test_a_dial_code_bridges_to_the_option_that_carries_it():
    assert bridge_option("+91", DIAL_LIST) == "+91 (India)"    # two carriers: the least-qualified one
    assert bridge_option("+91", ["🇦🇬 (+1 268) Antigua and Barbuda", "🇮🇳 (+91) India", "🇮🇹 (+39) Italy"]) == "🇮🇳 (+91) India"
    assert fit_option("Country Phone Code", "+91",
                      ["India (+91)", "+1 (United States)", "United States (+1)"], {}) == "India (+91)"


def test_the_real_referral_pair_and_its_single_survivor():
    opts = ["LinkedIn", "Indeed", "Google", "Referral", "Job Board - Other", "Other"]
    assert bridge_option("Job Board", opts) == "Job Board - Other"
    # the value parked exactly inside one option's wording
    assert bridge_option("Job Board", ["LinkedIn", "Job board (LinkedIn)"]) == "Job board (LinkedIn)"


def test_multi_qualifier_survivors_take_the_least_qualified_option():
    assert bridge_option("Job Board", ["LinkedIn job board posting", "Job Board - Other"]) == "Job Board - Other"
    assert bridge_option("Other - please specify", ["Job Board - Other", "Other"]) == "Other"


def test_one_survivor_of_the_pith_direction_takes_the_pith():
    assert bridge_option("LinkedIn (via a referral)", ["LinkedIn"]) == "LinkedIn"
    assert bridge_option("Mumbai Maharashtra India", ["Mumbai", "Delhi"]) == "Mumbai"


def test_survivors_that_mean_different_things_are_never_bridged():
    # one survivor each way: 'LinkedIn' sits inside the value while an option
    # wraps the whole value — two different things at once, old matchers decide
    assert bridge_option("Job Board (LinkedIn)", ["LinkedIn", "Job Board (LinkedIn) - Other"]) is None
    # no phrasing overlap at all: a category semantic the bridge must not invent
    assert bridge_option("Job Board", ["LinkedIn", "Indeed"]) is None
    assert bridge_option("Senior Data Scientist", ["Data Science / Analytics"]) is None
    assert fit_option("Role fit", "Senior Data Scientist",
                      ["Data Science / Analytics", "Engineering", "Operations"], {}, None) is None


def test_qualifiers_that_change_the_meaning_are_not_bridged():
    opts = ["Self-Employed", "Employed - Full Time"]
    assert bridge_option("Employed", opts) == "Employed - Full Time"      # the benign variant is left
    assert bridge_option("Employed", ["Self-Employed", "Student"]) is None  # nothing safe: old matchers decide
    assert bridge_option("Non-Technical Role", ["Technical"]) is None       # the stripped flank was the meaning


def test_a_plus_is_never_stripped_and_never_band_matches():
    # red-team A-1: '91' without '+' cannot walk into '+91', and a fuller +code
    # cannot fuzz-match another dial code through its digits
    assert bridge_option("91", DIAL_LIST) is None
    assert bridge_option("+9", DIAL_LIST) is None
    assert bridge_option("+93", DIAL_LIST) is None
    assert bridge_option("9876543210", DIAL_LIST) is None                  # a phone number is not a code


def test_bridge_runs_before_the_llm_and_after_the_exact_pass():
    calls = []
    llm = lambda p: calls.append(p) or "LinkedIn"
    assert fit_option("How did you hear about us?", "Job Board",
                      ["Job board (LinkedIn)", "Other"], {}, llm) == "Job board (LinkedIn)"
    assert not calls                                        # deterministic: no model spent
    assert fit_option("q", "Yes", ["Yes", "No"], {}, llm) == "Yes"          # rung 1 untouched
    assert fit_option("How did you hear?", "Job Board",
                      ["Job portal (LinkedIn)", "Company website"],
                      {"Job Board": ["Job portal"]}) == "Job portal (LinkedIn)"   # synonyms feed the bridge
    assert not calls
    assert fit_option("Phone", "+91 9876501234", [], {}) == "+91 9876501234"     # no options: raw, as today


# ── the empty-options shape gate ─────────────────────────────────────────────

def test_dial_intent_is_read_from_the_label_not_a_renamed_shape():
    assert dial_label("Country Phone Code*")
    assert dial_label("Country code") and dial_label("Dialing code")
    assert dial_label("Phone country code") and dial_label("Phone Code")
    assert not dial_label("Phone number (with country code)")     # the label wants the whole number
    assert not dial_label("Phone") and not dial_label("Mobile Number")
    assert infer_shape(None, "", "", "Country Phone Code*") == "phone"   # the shape tier stays as it was


def test_the_30901_dial_code_now_answers_confident(qbank_conn, fake_embed, make_field):
    _seed(qbank_conn, fake_embed, "country_phone_code", "Country Phone Code*", "+91")
    m, v = answer_field(qbank_conn, make_field("Country Phone Code*", "combobox"), embed=fake_embed)
    assert (m.band, m.kind, v) == (CONFIDENT, "exact", "+91")     # no 'likely: shape phone failed'
    assert m.note == ""


def test_a_dial_code_missing_its_plus_is_completed_and_audited(qbank_conn, fake_embed, make_field):
    _seed(qbank_conn, fake_embed, "country_phone_code", "Country Phone Code*", "91")
    m, v = answer_field(qbank_conn, make_field("Country Phone Code*", "combobox"), embed=fake_embed)
    assert (m.band, v) == (CONFIDENT, "+91")
    assert "dial code written as '+91'" in m.note


def test_a_country_name_is_written_as_the_code_its_own_synonyms_store(qbank_conn, fake_embed, make_field):
    _seed(qbank_conn, fake_embed, "country_phone_code", "Country Phone Code*", "India",
          synonyms={"India": ["+91"]})
    m, v = answer_field(qbank_conn, make_field("Country Phone Code*", "combobox"), embed=fake_embed)
    assert (m.band, v) == (CONFIDENT, "+91")
    assert "dial code '+91' read from the stored answer" in m.note
    # a stored answer carrying country AND code is distilled to the code itself
    _seed(qbank_conn, fake_embed, "dial_code", "Country dialing code", "India +91 / (India)")
    m, v = answer_field(qbank_conn, make_field("Country dialing code", "combobox"), embed=fake_embed)
    assert (m.band, v) == (CONFIDENT, "+91") and "read from the stored answer" in m.note


def test_an_unshapable_dial_answer_escalates_with_a_crisp_basis(qbank_conn, fake_embed, make_field):
    _seed(qbank_conn, fake_embed, "country_phone_code", "Country Phone Code*", "India")
    m, v = answer_field(qbank_conn, make_field("Country Phone Code*", "combobox"), embed=fake_embed)
    assert (m.band, v) == (NONE, None)                    # today's unsupported signal: no value
    assert "no options to fit" in m.note and "'India'" in m.note


def test_a_full_number_label_refuses_a_bare_dial_code(qbank_conn, fake_embed, make_field):
    _seed(qbank_conn, fake_embed, "phone_primary", "Phone Number", "+91")
    m, v = answer_field(qbank_conn, make_field("Phone Number", "combobox"), embed=fake_embed)
    assert (m.band, v) == (NONE, None)
    assert "reads as a dial code" in m.note and "no options to fit" in m.note
    _seed(qbank_conn, fake_embed, "phone_short", "Phone", "98765")
    m, v = answer_field(qbank_conn, make_field("Phone", "combobox"), embed=fake_embed)
    assert (m.band, v) == (NONE, None) and "no options to fit" in m.note


def test_two_stored_dial_codes_never_guess(qbank_conn, fake_embed, make_field):
    _seed(qbank_conn, fake_embed, "country_phone_code", "Country Phone Code*", "India",
          synonyms={"India": ["+91", "+39"]})
    m, v = answer_field(qbank_conn, make_field("Country Phone Code*", "combobox"), embed=fake_embed)
    assert (m.band, v) == (NONE, None) and "supplies none" in m.note


def test_text_typed_values_keep_todays_flagged_fill(qbank_conn, fake_embed, make_field):
    # non-phone shapes with no options: typed and flagged exactly as before
    m, v = answer_field(qbank_conn, make_field("LinkedIn profile URL"), embed=fake_embed)
    assert (m.band, v) == (LIKELY, "linkedin.com/in/x") and "shape url" in m.note
    m, v = answer_field(qbank_conn, make_field("Notice period", input_type="email"), embed=fake_embed)
    assert (m.band, v) == (LIKELY, "30") and "shape email" in m.note
