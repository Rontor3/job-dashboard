import json
import sqlite3
from datetime import date, timedelta

from career_agent.memory import facts as F
from career_agent.memory import factcards as FC
from career_agent.memory import qbank
from career_agent.memory.qbank_promote import promote_answer

YN = ["Yes", "No"]


def _bank(fake_embed, entries=()):
    c = sqlite3.connect(":memory:")
    qbank.ensure(c)
    for e in entries:
        qbank.upsert_entry(c, e)
        if e.get("answer"):
            qbank.set_answer(c, e["id"], e["answer"])
        qbank.add_wording(c, e["question"], e["id"], fake_embed([e["question"]])[0], "seed")
    return c


BASE = [{"id": "join_buffer_days", "question": "Days you need between notice end and joining", "atype": "number",
         "answer": "15"},
        {"id": "career_start", "question": "When your career started", "atype": "date", "answer": "01/08/2023"},
        {"id": "relocation_places", "question": "Which places are you willing to relocate to?", "atype": "choice",
         "rule": "preference", "answer": "India", "synonyms": {"India": ["gurugram", "hyderabad"]}}]
CONTACT = {"full_name": "Asha Rao", "notice_period": "30 days", "location": "Mumbai, India"}


def test_fixes_place_year_letters_windows_names(fake_embed):
    facts = F.build(_bank(fake_embed, BASE), CONTACT)
    gurugram = {"op": "contains", "args": [{"fact": "relocation_places"}, "Gurugram, Haryana"]}
    assert F.run(gurugram, facts) is True                                   # a city inside a listed region
    assert F.run({"op": "contains", "args": [{"fact": "relocation_places"}, "Dubai"]}, facts) is False
    assert F.render(date(2001, 3, 17), (), label="Year of birth") == "2001"
    assert F.render(date(2001, 3, 17), (), label="Date of birth") == "17/03/2001"
    assert F.render(True, ["Y", "N"], label="Authorized?") == "Y"
    opts = ["Immediately", "Within 30 days", "31-60 days", "More than 2 months"]
    assert F.render(30.0, opts) == "Within 30 days" and F.render(45.0, opts) == "31-60 days"
    assert F.render(90.0, opts) == "More than 2 months" and F.render(3.0, ["3", "5"]) == "3"   # not windows
    assert (facts["first_name"]["value"], facts["last_name"]["value"]) == ("Asha", "Rao")


def test_derived_facts_are_computed_never_stored(fake_embed):
    facts = F.build(_bank(fake_embed, BASE), CONTACT)
    today = facts["today"]["value"]
    assert facts["earliest_start"]["value"] == today + timedelta(days=45)  # notice 30 + joining buffer 15
    assert facts["last_working_day"]["value"] == today + timedelta(days=30)
    assert facts["experience_months"]["value"] >= 38                       # Aug 2023 -> today (>= Oct 2026)
    assert "earliest_start" not in F.build(_bank(fake_embed), {})          # no notice period -> no derived card
    bare = F.build(_bank(fake_embed), {"notice_period": "30 days"})        # joining buffer: the default 15 days
    assert bare["earliest_start"]["value"] == bare["today"]["value"] + timedelta(days=45)


def test_bare_value_label_reads_the_field_id():
    assert FC.question_of("+91", "#phone_number_field_number") == "phone number field number"
    assert FC.question_of("Mobile", "#m") == "Mobile"


def _gate(local_reply, plan_reply, fake_embed, question="Do you live in India?", options=YN):
    facts = F.build(_bank(fake_embed, BASE), CONTACT)
    cards = FC.Cards(facts, fake_embed)
    haiku = plan_reply if callable(plan_reply) else (lambda p: plan_reply)
    return FC.answer(question, "radio_group", options, {}, facts, cards,
                     local_llm=lambda p: local_reply, haiku_llm=haiku)


def test_gate_fills_only_when_the_readers_agree(fake_embed):
    plan = json.dumps({"plan": {"op": "cmp", "cmp": "==", "args": [{"fact": "location", "field": "country"},
                                                                    "India"]}})
    assert _gate('{"value": "Yes", "card": "location"}', plan, fake_embed)[0] == "Yes"
    value, note = _gate('{"value": "No", "card": "location"}', plan, fake_embed)
    assert value is None and note.startswith("disagree")
    assert _gate("NONE", plan, fake_embed)[1].startswith("plan only")      # local had nothing: checked plan alone
    missing = json.dumps({"missing": {"key": "passport_valid", "type": "bool", "ask": "Valid passport?"}})
    assert _gate('{"value": "Yes", "card": "location"}', missing, fake_embed)[0] is None   # Haiku veto
    down = lambda p: (_ for _ in ()).throw(RuntimeError("login expired"))
    value, note = _gate('{"value": "Yes", "card": "location"}', down, fake_embed)
    assert value is None and "escalate" in note                            # fail closed


def test_a_reply_is_saved_once_as_the_named_fact(fake_embed, make_field):
    c = _bank(fake_embed, BASE)
    f = make_field("Do you hold a valid passport for international travel?", kind="radio_group", options=YN)
    miss = {"key": "passport_valid", "type": "bool", "ask": "Do you hold a valid passport?", "company": "Acme"}
    assert promote_answer(c, f, "Yes", fake_embed, missing=miss) == "passport_valid"
    assert F.build(c, CONTACT)["passport_valid"]["value"] is True          # a card, available at once
    again = make_field("Do you hold a valid passport?", kind="radio_group", options=YN)
    assert promote_answer(c, again, "Yes", fake_embed, missing={**miss, "key": "has_passport"}) == "passport_valid"
    assert qbank.get_entry(c, "has_passport") is None                     # near card: wording linked, no 2nd card
    indeed = make_field("Indeed", kind="checkbox")
    assert promote_answer(c, indeed, "Yes", fake_embed,
                          missing={"key": "found_on_indeed", "type": "bool", "ask": "Did you find this job on Indeed?"}) is None


def test_a_derived_fact_proposed_once_is_kept(fake_embed, make_field):
    from career_agent.memory.qbank_memory import QBankMemory
    c = _bank(fake_embed, BASE)
    derive = {"derive": {"key": "experience_years_now", "type": "number", "desc": "total experience in years",
                         "plan": {"op": "months_between", "args": [{"fact": "career_start"}, {"fact": "today"}],
                                  "unit": "year"}}}
    mem = QBankMemory(c, embed=fake_embed, contact=CONTACT, facts_llm=lambda p: json.dumps(derive))
    f = make_field("Total years of professional experience (decimal)", ref="#y")
    (d,), _ = mem.recall([f])
    assert float(d.value) >= 3.2
    e = qbank.get_entry(c, "experience_years_now")
    assert e["rule"] == "derived" and not e.get("answer")                 # the formula is kept, not the value
    assert "experience_years_now" in F.build(c, CONTACT)


def test_regression_fixes_units_and_agreement(fake_embed):
    facts = F.build(_bank(fake_embed, BASE), CONTACT)
    assert facts["days_to_join"]["value"] == 45.0                          # notice 30 + buffer 15
    weeks = F.answer("Notice period in weeks", "text", [], {}, facts, lambda p: '{"plan": {"fact": "notice_period"}}')
    assert weeks[0] == "4.3"                                               # days -> weeks, not '30'
    days = F.answer("Available To Join (in days)", "text", [], {}, facts, lambda p: '{"plan": {"fact": "earliest_start"}}')
    assert days[0] == "45"                                                 # a date -> days from today
    assert FC._same("25 LPA", "25") and FC._same("35 LPA", "3500000") and FC._same("+91 7565052330", "7565052330")
    assert not FC._same("25 LPA", "35") and not FC._same("Yes", "No")


def test_one_reader_alone_does_not_fill(fake_embed):
    value, note = _gate('{"value": "Yes", "card": "location"}', '{}', fake_embed)    # plan unreadable, local only
    assert value is None and note.startswith("local only")
