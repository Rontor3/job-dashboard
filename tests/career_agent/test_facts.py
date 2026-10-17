from datetime import date

import pytest

from career_agent.memory import facts as F

FACTS = {
    "dob": F._fact("date", date(2001, 3, 17), ""),
    "today": F._fact("date", date(2026, 10, 11), ""),
    "phone": F._fact("phone", F.phone("+91 7565052330"), ""),
    "location": F._fact("place", F.place("Mumbai, India"), ""),
    "current_ctc": F._fact("money", F.money("25 LPA"), ""),
    "skills": F._fact("map", {"python": 3.0, "sql": 2.0}, ""),
    "languages": F._fact("map", {"english": "fluent", "hindi": None}, ""),
    "local_cities": F._fact("list", ["Mumbai", "Bengaluru"], ""),
}


def ans(plan, options=()):
    return F.render(F.run(plan, FACTS), options)


def test_plans_over_facts():
    assert ans({"op": "cmp", "cmp": ">=", "args": [{"op": "age", "args": [{"fact": "dob"}]}, 18]}) == "Yes"
    assert ans({"fact": "phone", "field": "dial"}) == "+91"
    assert ans({"op": "cmp", "cmp": "==", "args": [{"fact": "location", "field": "country"}, "India"]}) == "Yes"
    assert ans({"op": "lookup", "args": [{"fact": "skills"}, "ROS"], "default": 0}) == "0"
    assert ans({"op": "lookup", "args": [{"fact": "skills"}, "Python"], "default": 0}) == "3"
    lvl = {"op": "lookup", "args": [{"fact": "languages"}, "english"]}
    assert ans({"op": "level_at_least", "args": [lvl, "fluent"]}) == "Yes"
    usd = {"op": "money", "args": [{"fact": "current_ctc"}], "currency": "USD", "period": "month"}
    assert ans({"op": "cmp", "cmp": ">", "args": [usd, 3500]}) == "No"          # ~2,367 USD/month
    assert ans({"op": "money", "args": [{"fact": "current_ctc"}], "unit": "lakh"}) == "25"
    assert ans({"op": "contains", "args": [{"fact": "local_cities"}, "bengaluru"]}, ["Yes", "No"]) == "Yes"


def test_model_shorthand():
    assert ans({"op": "lookup", "args": ["skills", "python"], "default": 0}) == "3"     # bare fact name
    assert ans("phone.dial") == "+91"
    assert ans({"op": "level_at_least", "args": ["english", "fluent"]}) == "Yes"       # language name
    six = {"op": "amount", "value": 6, "unit": "lakh"}
    assert ans({"op": "cmp", "cmp": "<=", "args": ["current_ctc", six]}) == "No"
    assert not F.uses_fact({"op": "cmp", "cmp": "==", "args": ["Siemens", "Siemens"]}, FACTS)


def test_yes_no_only_into_a_yes_no_field():
    assert F.render(True, (), label="Pursuing/ Completed *") is None            # wants a word, not Yes
    assert F.render(True, (), label="Have you completed a degree?") == "Yes"
    assert F.render(False, ["Yes", "No"], label="Visa sponsorship") == "No"     # yes/no options say it is one


def test_a_tick_box_takes_a_yes_no_plan():
    plan = '{"plan": {"fact": "willing_to_relocate"}}'
    facts = {"willing_to_relocate": F._fact("bool", True, ""), "today": FACTS["today"]}
    label = "This role doesn't match your location preferences. Check here if you're open to relocating"
    assert F.answer(label, "checkbox", [], {}, facts, lambda p: plan)[0] == "Yes"      # live YC miss, 2026-10-12
    assert F.answer(label, "text", [], {}, facts, lambda p: plan)[0] is None          # a text box wants a word


def test_qbank_memory_falls_back_to_a_plan(qbank_conn, fake_embed):
    from career_agent.browser.form_model import Field
    from career_agent.memory.qbank_memory import QBankMemory
    plan = '{"plan": {"op": "cmp", "cmp": "==", "args": [{"fact": "location", "field": "country"}, "India"]}}'
    mem = QBankMemory(qbank_conn, embed=fake_embed, contact={"location": "Mumbai, India"}, facts_llm=lambda p: plan)
    f = Field(ref="r", kind="radio_group", label="Do you live in India right now?", required=True, options=["Yes", "No"])
    decisions, still = mem.recall([f])
    assert [(d.value, d.source) for d in decisions] == [("Yes", "qbank_likely")] and still == []
    assert "from your facts: plan only" in mem.explain(f)["basis"]
    off = QBankMemory(qbank_conn, embed=fake_embed, contact={"location": "Mumbai, India"})   # flag off: unchanged
    assert off.recall([f])[0] == []


def test_never_guesses():
    with pytest.raises(F.PlanError):                                             # 25 LPA vs "3500" of what?
        F.run({"op": "cmp", "cmp": ">", "args": ["current_ctc", 3500]}, FACTS)
    with pytest.raises(F.PlanError):
        F.run({"fact": "alternate_phone"}, FACTS)                                # no such fact
    with pytest.raises(F.PlanError):
        F.run({"op": "lookup", "args": [{"fact": "skills"}, "ros"]}, FACTS)      # absent, no default given
    with pytest.raises(F.PlanError):                                             # level not given
        F.run({"op": "level_at_least", "args": [{"op": "lookup", "args": [{"fact": "languages"}, "hindi"]}, "fluent"]}, FACTS)


def test_live_keka_formatting():
    """Values the facts tier wrote into a live Keka form (2026-10-12), now in the shape each field wants."""
    assert F.render({"python": 3.0, "sql": 2.0, "ros": 0}, label="Skills") == "python, sql"     # names, not '3.0, 2.0'
    ctc = F.money("25 LPA")
    assert F.render(ctc, label="Current Salary", hint="Current Salary currentSalary.amount") == "2500000"
    assert F.render(ctc, label="Current CTC (in lakhs)", hint="Current CTC (in lakhs)") == "25"
    assert F.render(ctc, label="What is your current CTC?", hint="What is your current CTC?") == "25 LPA"
    facts = {"dob": F._fact("date", date(2001, 3, 17), ""), "today": FACTS["today"]}
    assert F.answer("JanFebMarAprMayJunJulAugSepOctNovDec", "select", [], {}, facts,
                    lambda p: '{"plan": {"fact": "dob"}}')[0] is None             # glued option words are not a label


def test_an_instruction_reaches_the_compiler_and_gets_its_own_cache_slot():
    seen, cache = [], {}

    class Cache(dict):
        def get(self, k):
            return dict.get(self, k)

    cache = Cache()
    llm = lambda p: seen.append(p) or '{"plan": {"fact": "phone", "field": "dial"}}'     # noqa: E731
    facts = {**FACTS, "phone": F._fact("phone", F.phone("+91 7565052330"), "phone")}
    F.answer("Country code", "text", [], {}, facts, llm, cache=cache)
    F.answer("Country code", "text", [], {}, facts, llm, cache=cache, guidance="only the dial code, no number")
    assert len(seen) == 2 and "only the dial code" in seen[1] and "only the dial code" not in seen[0]
    assert len(cache) == 2                                # the plain plan is not reused for the instructed one


def test_job_facts_let_a_plan_compare_the_job_with_the_applicant():
    facts = {**FACTS, "location": F._fact("place", F.place("Mumbai, India"), "location"),
             **F.job_facts({"location": "Ahmedabad, Gujarat, India", "company": "Acme"})}
    plan = ('{"plan": {"op": "cmp", "cmp": "==", "args": [{"fact": "location", "field": "city"}, '
            '{"fact": "job_location", "field": "city"}]}}')
    assert F.answer("Are you currently based in Ahmedabad?", "radio_group", ["Yes", "No"], {}, facts,
                    lambda p: plan)[0] == "No"
    assert "Ahmedabad" not in F.schema(facts)             # the compiler sees names, never the job's values
