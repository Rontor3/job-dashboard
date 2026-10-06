import sqlite3
from datetime import date
from types import SimpleNamespace as NS

import pytest

from career_agent.memory import qbank
from career_agent.memory.qbank_compose import build_prompt, compose, related_facts
from career_agent.memory.qbank_match import LIKELY, NONE, answer_field

TODAY = date(2026, 10, 4)


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch):
    """answer_field calls date.today() itself: pin it, or every expected date moves with the calendar."""
    from career_agent.memory import qbank_compose

    class _Pinned(date):
        @classmethod
        def today(cls):
            return TODAY
    monkeypatch.setattr(qbank_compose, "date", _Pinned)


@pytest.fixture
def bank():
    c = sqlite3.connect(":memory:")
    qbank.ensure(c)
    return _bank(c)


def _bank(c):
    qbank.upsert_entry(c, {"id": "notice_period", "question": "What is your notice period?", "topic": "availability",
                           "atype": "number", "profile_ref": "notice_period"})
    qbank.upsert_entry(c, {"id": "last_working_day", "question": "What is your last working day?",
                           "topic": "availability", "atype": "date"})          # no value of its own
    return c


def _field(label, kind="text", input_type="", options=None):
    return NS(label=label, description="", kind=kind, input_type=input_type, options=options or [], purpose=None,
              ref="r", autocomplete="", required=False)


def _embed(texts):
    """Controlled vectors: notice-period and last-working-day wordings are related (cos 0.6), the rest unrelated."""
    import numpy as np
    out = []
    for t in texts:
        t = t.lower()
        out.append([1.0, 0.0, 0.0] if "notice" in t else [0.6, 0.8, 0.0] if ("last working" in t or "resigned" in t) else [0.0, 0.0, 1.0])
    return np.array(out, dtype="float32")


def _seed(c, fake_embed=None):
    for eid, q in (("notice_period", "What is your notice period?"), ("last_working_day", "What is your last working day?")):
        qbank.add_wording(c, q, eid, _embed([q])[0], "seed")


def _model(p):
    """Answers only when the notice period is among the facts it was given."""
    return '{"days_from_today": 30}' if "notice period? 30 days" in p else '{"value": null}'


def test_related_facts_are_the_stored_values_nearest_the_question(bank):
    c = bank; _seed(c)
    facts = related_facts(c, "Last working day", embed=_embed, exclude={"last_working_day"},
                          resolve=lambda e: {"notice_period": "30 days"}.get(e["id"]))
    assert [(q, v) for q, v, _ in facts] == [("What is your notice period?", "30 days")]


def test_prompt_carries_today_the_field_format_and_the_facts():
    p = build_prompt("What is your last working day?", _field("x", "date", "date"),
                     [("What is your notice period?", "30 days", 0.7)], TODAY)
    assert "2026-10-04" in p and "days_from_today" in p and "notice period? 30 days" in p and "null" in p


def test_compose_returns_the_models_value_or_none():
    f = _field("x")
    facts = [("What is your notice period?", "30 days", 0.7)]
    assert compose("q", f, facts, lambda p: ' {"value": " 30 "} ', TODAY) == "30"                 # grounded: 30 is in the fact
    assert compose("q", f, facts, lambda p: '<think>hm</think>{"value": null}', TODAY) is None
    assert compose("q", f, facts, lambda p: "I think maybe the 3rd", TODAY) is None      # chatter is not a value
    assert compose("q", f, facts, lambda p: '{"value": "a\\nb"}', TODAY) is None
    assert compose("q", f, [], lambda p: '{"value": "x"}', TODAY) is None                # no facts -> never asks
    assert compose("q", f, facts, None, TODAY) is None

    def boom(p): raise TimeoutError
    assert compose("q", f, facts, boom, TODAY) is None


def test_a_date_counted_from_today_is_worked_out_in_code_in_the_format_asked():
    facts = [("What is your notice period?", "30 days", 0.7)]
    ask = lambda q: compose(q, _field("x", "date", "date"), facts, lambda p: '{"days_from_today": 30}', TODAY)
    assert ask("What is your last working day?") == "2026-11-03"                          # the model never writes a date
    assert ask("Last working date (dd/mm/yyyy)") == "2026-11-03"                          # a real date input takes ISO whatever the label says
    assert compose("Last working date (dd/mm/yyyy)", _field("x"), facts, lambda p: '{"days_from_today": 30}', TODAY) == "03/11/2026"
    assert compose("q", _field("x"), facts, lambda p: '{"days_from_today": "30"}', TODAY) is None   # must be a number
    assert compose("How soon can you join? (in days)", _field("x", "number", "number"), facts,
                   lambda p: '{"days_from_today": 30}', TODAY) == "30"                          # number field: the count, not a date
    assert compose("q", _field("x"), facts, lambda p: '{"days_from_today": 99999}', TODAY) is None  # absurd -> refused


def test_answer_field_composes_when_the_entry_has_no_value_and_marks_it_likely(bank):
    c = bank; _seed(c)
    m, v = answer_field(c, _field("What is your last working day?", "date", "date"), embed=_embed, llm=_model,
                        contact={"notice_period": "30 days"})
    assert v == "2026-11-03" and m.band == LIKELY and "notice period" in m.note


def test_without_facts_or_a_model_it_is_still_flagged(bank):
    c = bank; _seed(c)
    f = _field("What is your last working day?", "date", "date")
    assert answer_field(c, f, embed=_embed, llm=_model, contact={})[0].band == NONE      # no notice stored -> nothing to compose from
    assert answer_field(c, f, embed=_embed, llm=None, contact={"notice_period": "30 days"})[0].band == NONE


def test_a_question_that_matches_no_entry_still_gets_composed_from_clearly_related_facts(bank):
    import numpy as np
    _seed(bank)
    # similar enough to the notice-period wording to count as a related fact (0.55), too far to be that question (floor 0.6)
    near = lambda texts: np.array([[0.55, 0.0, 0.835]] * len(texts), dtype="float32")
    f = _field("Please state your date of availability", "text")
    m, v = answer_field(bank, f, embed=near, llm=_model, contact={"notice_period": "30 days"})
    assert (m.band, m.kind, v) == (LIKELY, "composed", "2026-11-03")
    far = lambda texts: np.array([[0.2, 0.0, 0.98]] * len(texts), dtype="float32")        # 0.2: unrelated -> no model call
    calls = []
    answer_field(bank, f, embed=far, llm=lambda p: calls.append(p) or "x", contact={"notice_period": "30 days"})
    assert calls == []


def test_yes_no_questions_are_never_composed(bank):
    qbank.upsert_entry(bank, {"id": "resigned", "question": "Have you already resigned?", "topic": "availability", "atype": "bool"})
    _seed(bank)
    qbank.add_wording(bank, "Have you already resigned?", "resigned", _embed(["Have you already resigned?"])[0], "seed")
    calls = []
    f = _field("Have you already resigned?", "radio", options=["Yes", "No"])
    m, v = answer_field(bank, f, embed=_embed, llm=lambda p: calls.append(p) or "No", contact={"notice_period": "30 days"})
    assert v is None and calls == []                      # a statement about you is stated, never worked out


def test_facts_on_the_same_topic_are_retrieved_whatever_the_wording(bank):
    _seed(bank)
    qbank.upsert_entry(bank, {"id": "other", "question": "Favourite colour", "topic": "misc", "atype": "text", "answer": "blue"})
    facts = related_facts(bank, "Earliest joining date", embed=lambda ts: _embed(["unrelated"] * len(ts)),
                          resolve=lambda e: {"notice_period": "30 days", "other": "blue"}.get(e["id"]), topic="availability")
    assert [(q, v) for q, v, _ in facts] == [("What is your notice period?", "30 days")]     # same topic in, other topic out


def test_a_composed_text_value_must_come_from_the_fact_values():
    facts = [("What is your phone type?", "Mobile", 0.6), ("What is your notice period?", "30 days", 0.5)]
    f = _field("Contact Number")
    assert compose("Contact Number", f, facts, lambda p: '{"value": "mobile number"}', TODAY) is None   # echoes the label
    assert compose("Phone type", f, facts, lambda p: '{"value": "Mobile"}', TODAY) == "Mobile"           # in a fact value
    assert compose("Notice", f, facts, lambda p: '{"value": "30"}', TODAY) == "30"                       # its number is in a fact
    assert compose("Notice", f, facts, lambda p: '{"value": "45 days"}', TODAY) is None                  # invented number


def test_an_unmatched_field_with_a_known_purpose_is_left_to_the_rule_mapper(bank):
    import numpy as np
    _seed(bank)
    f = _field("Contact Number")
    f.purpose = "phone"
    near = lambda texts: np.array([[0.55, 0.0, 0.835]] * len(texts), dtype="float32")   # related, but matches no entry
    calls = []
    m, v = answer_field(bank, f, embed=near, llm=lambda p: calls.append(p) or '{"value": "30 days"}',
                        contact={"notice_period": "30 days"})
    composed = lambda: [c for c in calls if "Facts about the candidate" in c]     # entry-matching prompts do not count
    assert v is None and composed() == []
    f.purpose = None                                    # without a purpose the same field IS composed from the facts
    m, v = answer_field(bank, f, embed=near, llm=lambda p: calls.append(p) or '{"value": "30 days"}',
                        contact={"notice_period": "30 days"})
    assert v == "30 days" and composed()


def test_date_question_takes_only_a_day_count_and_code_writes_the_date():
    from datetime import date
    from career_agent.memory.qbank_compose import asks_for_date, compose
    f = type("F", (), {"kind": "text", "input_type": "", "options": []})()
    facts = [("What is your notice period (in days)?", "30 days", 1.0)]
    today = date(2026, 10, 5)
    assert asks_for_date("Last working day (dd-mm-yyyy)", f) and asks_for_date("Joining date", f)
    assert not asks_for_date("Date of birth", f) and not asks_for_date("Graduation date", f)
    # the model's own date is refused; only its day count is used
    assert compose("Last working day (dd-mm-yyyy)", f, facts, lambda p: '{"value": "2026-10-04"}', today) is None
    assert compose("Last working day (dd-mm-yyyy)", f, facts, lambda p: '{"days_from_today": 30}', today) == "04-11-2026"
    assert compose("Joining date", f, facts, lambda p: '{"days_from_today": 30}', today) == "2026-11-04"
    assert compose("Joining date", f, facts, lambda p: '{"days_from_today": null}', today) is None


def test_date_format_is_read_from_the_page_not_assumed():
    from datetime import date
    from career_agent.memory.qbank_compose import _date_text, date_format_from, asks_for_date
    d = date(2026, 11, 4)
    F = lambda **kw: type("F", (), {"kind": "text", "input_type": "", "description": "", "placeholder": "", "options": [], **kw})()
    assert date_format_from("DD/MM/YYYY") == "%d/%m/%Y" and date_format_from("mm-dd-yy") == "%m-%d-%y"
    assert date_format_from("dd MMM yyyy") == "%d %b %Y" and date_format_from("MM/DD") is None
    assert _date_text(d, "Joining date", F(placeholder="DD/MM/YYYY")) == "04/11/2026"       # format only in the placeholder
    assert _date_text(d, "Joining date", F(description="Use the format mm/dd/yyyy")) == "11/04/2026"   # helper text
    assert _date_text(d, "Joining date (dd/mm/yyyy)", F(input_type="date")) == "2026-11-04"  # a date input takes ISO whatever the label says
    assert _date_text(d, "Joining date", F()) == "2026-11-04"
    assert asks_for_date("Start", F(placeholder="DD/MM/YYYY")) and not asks_for_date("Start", F())
