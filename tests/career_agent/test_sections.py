"""Section-wise answering: one local + one Haiku call per section, the same per-field gate as the one-field path."""
import json
from datetime import date

from career_agent.browser.form_model import Field
from career_agent.memory import facts as F
from career_agent.memory import sections as S
from career_agent.memory.factcards import Cards


def fld(ref, label, kind="text", section="Contact Information", row=-1, options=(), **kw):
    return Field(ref, kind, label, False, list(options), section=section, row=row, **kw)


FACTS = {
    "first_name": F._fact("text", "Rakshit", "first / given name"),
    "notice_period": F._fact("days", 30.0, "notice period in days"),
    "sponsorship_required": F._fact("bool", False, "needs visa sponsorship"),
    "today": F._fact("date", date(2026, 10, 18), "today's date"),
}


def embed(texts):
    import numpy as np
    out = np.zeros((len(texts), 64), dtype="float32")
    for i, t in enumerate(texts):
        for w in t.lower().split():
            out[i, hash(w) % 64] += 1
    n = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.where(n == 0, 1, n)


class Calls:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return json.dumps(self.reply(prompt) if callable(self.reply) else self.reply)


class Cache(dict):
    def get(self, k):
        return dict.get(self, k)


def test_fields_are_grouped_by_section_and_entry_in_page_order_and_long_sections_split():
    fs = [fld("#a", "First Name"), fld("#b", "Degree", section="Education", row=0),
          fld("#c", "Last Name"), fld("#d", "Degree", section="Education", row=1)]
    assert [[f.ref for f in p] for p in S.packets(fs)] == [["#a", "#c"], ["#b"], ["#d"]]
    many = [fld(f"#{i}", f"Q{i}") for i in range(S.MAX_PER_PACKET + 3)]
    assert [len(p) for p in S.packets(many)] == [S.MAX_PER_PACKET, 3]
    assert S.title([fld("#d", "Degree", section="Education", row=1)]) == "Education — entry 2"


def test_each_field_goes_in_with_its_type_options_and_format():
    f = fld("#n", "Notice period", input_type="number", placeholder="days", max_length=3)
    line = S._field_line(1, f)
    assert "(text)" in line and "format: number, looks like 'days', max 3 chars" in line
    g = fld("#s", "Will you require sponsorship?", kind="radio_group", options=["Yes", "No"])
    assert "options: ['Yes', 'No']" in S._field_line(2, g)


def test_one_local_and_one_haiku_call_answer_the_whole_section_through_the_gate():
    packet = [fld("#fn", "First Name"), fld("#np", "Notice period (days)"),
              fld("#sp", "Will you require visa sponsorship?", kind="radio_group", options=["Yes", "No"]),
              fld("#gpa", "Your CGPA")]
    local = Calls({"F1": {"value": "Rakshit", "card": "first_name"}, "F2": {"value": "30", "card": "notice_period"},
                   "F3": {"value": "No", "card": "sponsorship_required"}, "F4": {"value": "NONE", "card": ""}})
    haiku = Calls({"F1": {"plan": {"fact": "first_name"}}, "F2": {"plan": {"fact": "notice_period"}},
                   "F3": {"plan": {"fact": "sponsorship_required"}},
                   "F4": {"missing": {"key": "cgpa", "type": "number", "ask": "Your CGPA"}}})
    cache = Cache()
    out = S.answer_packet(packet, {}, FACTS, Cards(FACTS, embed), local_llm=local, haiku_llm=haiku, cache=cache)
    assert len(local.prompts) == 1 and len(haiku.prompts) == 1                 # one call each for four fields
    assert out["#fn"][0] == "Rakshit" and out["#sp"][0] == "No" and out["#np"][0] in ("30", "30.0")
    assert out["#gpa"][0] is None and out["#gpa"][1].startswith("MISSING")
    assert "Rakshit" not in haiku.prompts[0]                                   # Haiku never sees a value
    # the same wordings again: every plan comes from the cache, no Haiku call at all
    S.answer_packet(packet, {}, FACTS, Cards(FACTS, embed), local_llm=local, haiku_llm=haiku, cache=cache)
    assert len(haiku.prompts) == 1


def test_disagreement_and_a_down_reader_escalate_per_field():
    packet = [fld("#fn", "First Name"), fld("#np", "Notice period (days)"),
              fld("#sp", "Will you require visa sponsorship?", kind="radio_group", options=["Yes", "No"])]
    local = Calls({"F1": {"value": "GenAI", "card": "first_name"}, "F2": {"value": "30", "card": "notice_period"},
                   "F3": {"value": "Yes", "card": "sponsorship_required"}})
    haiku = Calls({"F1": {"plan": {"fact": "first_name"}}, "F2": {"plan": {"fact": "notice_period"}},
                   "F3": {"plan": {"fact": "sponsorship_required"}}})
    out = S.answer_packet(packet, {}, FACTS, Cards(FACTS, embed), local_llm=local, haiku_llm=haiku)
    assert out["#fn"] == ("Rakshit", out["#fn"][1]) and "plan only" in out["#fn"][1]   # 'GenAI' is ungrounded
    assert out["#np"][0] in ("30", "30.0")
    assert out["#sp"][0] is None and "disagree" in out["#sp"][1]                # Yes vs the fact's No: escalate
    down = S.answer_packet(packet[:2], {}, FACTS, Cards(FACTS, embed), local_llm=lambda p: "garbage", haiku_llm=haiku)
    assert all(v is None and "unavailable" in n for v, n in down.values())     # fail closed
    def broken(prompt):
        raise RuntimeError("claude -p failed")
    gone = S.answer_packet(packet[:2], {}, FACTS, Cards(FACTS, embed), local_llm=local, haiku_llm=broken)
    assert all(v is None and "haiku unreachable" in n for v, n in gone.values())


def test_prime_uses_the_bank_first_then_one_pass_per_section(qbank_conn, fake_embed, monkeypatch):
    from career_agent.memory.qbank_memory import QBankMemory
    monkeypatch.setenv("CAREER_AGENT_SECTIONS", "1")
    local = Calls(lambda p: {"F1": {"value": "No", "card": "sponsorship_required"}})
    haiku = Calls(lambda p: {"F1": {"plan": {"fact": "sponsorship_required"}}})
    mem = QBankMemory(qbank_conn, embed=fake_embed, llm=local, facts_llm=haiku, contact={"location": "Mumbai, India"})
    monkeypatch.setattr(mem, "_fact_sheet", lambda: (FACTS, Cards(FACTS, fake_embed), Cache()))
    known = fld("#np", "Notice period")                                       # an exact bank wording: free
    asked = fld("#ws", "Would you ever need an employer to sponsor a work visa?", kind="radio_group",
                options=["Yes", "No"], section="Work authorization")
    mem.prime([known, asked])
    assert len(local.prompts) == 1 and len(haiku.prompts) == 1                 # one pass for the section, none for #np
    assert mem._answer(known)[1] == "30" and mem._answer(asked)[1] == "No"
    assert len(local.prompts) == 1                                            # _answer reused the cache


def test_prime_is_off_without_the_switch(qbank_conn, fake_embed, monkeypatch):
    from career_agent.memory.qbank_memory import QBankMemory
    monkeypatch.delenv("CAREER_AGENT_SECTIONS", raising=False)
    mem = QBankMemory(qbank_conn, embed=fake_embed, llm=Calls({}), facts_llm=Calls({}))
    mem.prime([fld("#x", "Anything")])
    assert mem._cache == {}


def test_model_calls_are_counted_per_name():
    from career_agent.orchestrator import claude_assist as ca
    ca._CALLS.clear()
    a, b = ca.counted(lambda p: "x", "local"), ca.counted(lambda p: "y", "haiku")
    a("1"), a("2"), b("3")
    assert ca._CALLS == {"local": 2, "haiku": 1}


def test_a_question_repeated_in_a_section_is_numbered_by_entry():
    from career_agent.browser.perception import _rows_by_repeat
    fs = [fld("#c1", "Current? *", kind="radio_group", section="Employment History"),
          fld("#n", "Notice", section="Employment History"),
          fld("#c2", "Current? *", kind="radio_group", section="Employment History"),
          fld("#p1", "In Progress", kind="radio_group", section="Education")]
    rows = {f.ref: f.row for f in _rows_by_repeat(fs)}
    assert rows["#c1"] == 0 and rows["#c2"] == 1 and rows["#n"] == -1 and rows["#p1"] == -1


def test_a_radio_group_with_no_named_option_is_a_hidden_template_not_a_question():
    from career_agent.browser.perception import to_form_model
    raw = [{"ref": "#a", "kind": "radio", "label": "Yes", "group": "g1", "group_label": "Current?", "required": True},
           {"ref": "#b", "kind": "radio", "label": "No", "group": "g1", "group_label": "Current?", "required": True},
           {"ref": "#c", "kind": "radio", "label": "", "group": "g2", "group_label": "Current?", "required": True},
           {"ref": "#d", "kind": "radio", "label": "", "group": "g2", "group_label": "Current?", "required": True}]
    groups = [f for f in to_form_model(raw) if f.kind == "radio_group"]
    assert [g.group for g in groups] == ["g1"]
