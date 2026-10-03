import json

from career_agent.memory.qbank import SEED_PATH
from career_agent.memory.qbank_rules import (NO_INPUT_RULES, RULE_HELP, RULES, RuleCtx,
                                             infer_shape, shape_ok)

BANK = {"home_address": "C-12, Sector 5, Noida 201301", "local_cities": "Noida, Delhi, Gurugram"}


def ctx(question="", answer=None, escape=None, job=None, bank=None, options=None, synonyms=None):
    b = bank or {}
    return RuleCtx(question, answer, escape, job or {}, lambda eid: b.get(eid),
                   options=options or [], synonyms=synonyms or {})


def test_local_or_escape():
    r = RULES["local_or_escape"]
    assert r(ctx(escape="relocating", job={"location": "San Francisco, CA"}, bank=BANK)) == "relocating"
    assert r(ctx(escape="relocating", job={"location": "Noida, Uttar Pradesh, India"}, bank=BANK)) == BANK["home_address"]
    assert r(ctx(escape="relocating", job={"location": "Remote, US"}, bank=BANK)) == BANK["home_address"]
    assert r(ctx(escape="relocating", job={}, bank=BANK)) is None           # unknown job city -> flag
    assert r(ctx(escape=None, job={"location": "London"}, bank=BANK)) is None  # not local, no escape -> flag


def test_empty_or_escape():
    r = RULES["empty_or_escape"]
    assert r(ctx(answer="none", escape="N/A")) == "N/A"
    assert r(ctx(answer="Kumar", escape="N/A")) == "Kumar"
    assert r(ctx(answer=None, escape="N/A")) is None                      # unanswered -> flag
    assert r(ctx(answer="none", escape=None)) is None


def test_company_in_list():
    r = RULES["company_in_list"]
    assert r(ctx(answer="none", job={"company": "Anthropic"})) == "No"
    assert r(ctx(answer="Google, Anthropic", job={"company": "Anthropic PBC"})) == "Yes"
    assert r(ctx(answer=None, job={"company": "Anthropic"})) is None
    assert r(ctx(answer="none", job={})) is None


def test_company_in_list_is_whole_word_not_substring():
    r = RULES["company_in_list"]
    assert r(ctx(answer="meta", job={"company": "Metamorphic"})) == "No"
    assert r(ctx(answer="Anthropic", job={"company": "Anthropic PBC"})) == "Yes"


def test_country_is_home_reuses_work_auth_logic():
    r = RULES["country_is_home"]
    assert r(ctx("Are you located in Canada?")) == "No"
    assert r(ctx("Are you legally authorized to work in India?")) == "Yes"
    assert r(ctx("Are you authorized to work in this country?")) is None


def test_years_in_skill():
    r = RULES["years_in_skill"]
    table = "python=3, machine learning=3, pytorch=2, default=2"
    assert r(ctx("How many years of experience do you have with PyTorch?", table)) == "2"
    assert r(ctx("Years of Python experience", table)) == "3"
    assert r(ctx("Years of experience with Rust", table)) == "2"
    assert r(ctx("Years with Rust", "python=3")) is None
    assert r(ctx("Years with Rust", None)) is None


def test_years_in_skill_prefers_earliest_mention_over_table_order():
    r = RULES["years_in_skill"]
    # table lists pytorch before python, but the question names python first
    table = "pytorch=5, python=3, default=1"
    assert r(ctx("Years of Python and PyTorch experience?", table)) == "3"


def test_shapes():
    assert infer_shape(None, "email", "", "") == "email"
    assert infer_shape(None, "", "shipping address-line1", "") == "address"
    assert infer_shape(None, "", "", "Street address, line 1") == "address"
    assert infer_shape("url", "tel", "", "") == "url"                      # entry shape wins
    assert infer_shape(None, "", "", "Where will you work from?") is None
    assert not shape_ok("address", "relocating")
    assert shape_ok("address", "relocating", escape="relocating")
    assert shape_ok("address", "C-12, Sector 5, Noida")
    assert not shape_ok("number", "30 LPA") and shape_ok("number", "30")
    assert not shape_ok("phone", "https://x") and shape_ok(None, "anything")


def test_seed_only_uses_known_rules():
    used = {e["rule"] for e in json.loads(SEED_PATH.read_text())["entries"] if e.get("rule")}
    assert used <= set(RULES) and NO_INPUT_RULES <= set(RULES) and set(RULE_HELP) == set(RULES)


ARR = "Remote > Hybrid > Onsite"
SYN = {"Remote": ["remote", "remotely", "work from home", "wfh"], "Hybrid": ["hybrid"],
       "Onsite": ["onsite", "on-site", "in office", "in-person", "from the office"]}


def pctx(question="", answer=ARR, options=None, synonyms=SYN):
    return RuleCtx(question, answer, None, {}, lambda e: None, options=options or [], synonyms=synonyms)


def test_preference_pick_one_takes_highest_ranked_offered():
    r = RULES["preference"]
    assert r(pctx(options=["Onsite", "Hybrid", "Remote"])) == "Remote"
    assert r(pctx(options=["On-site (office)", "Hybrid"])) == "Hybrid"
    assert r(pctx(options=["On-site (office)"])) == "On-site (office)"     # only onsite offered -> onsite is fine
    assert r(pctx(options=["Contract", "Intern"])) is None                 # nothing maps -> no answer


def test_preference_yes_no_uses_named_alternative():
    r = RULES["preference"]
    for q in ("Are you comfortable working in an onsite setting?", "Open to working remotely?",
              "Are you open to remote or hybrid roles?"):
        assert r(pctx(q, options=["Yes", "No"])) == "Yes", q
    assert r(pctx("Are you open to onsite?", answer="Remote > Hybrid; not: Onsite", options=["Yes", "No"])) == "No"
    assert r(pctx("Open to remote or onsite?", answer="Remote; not: Onsite")) is None      # mixed
    assert r(pctx("Are you open to the arrangement?", options=["Yes", "No"])) is None      # none named


def test_preference_text_and_unanswered():
    r = RULES["preference"]
    assert r(pctx("What is your preferred work mode?")) == "Remote"        # no options, none named -> top choice
    assert r(pctx("Open to onsite?", answer=None)) is None
    assert r(pctx("Open to onsite?", answer="")) is None
