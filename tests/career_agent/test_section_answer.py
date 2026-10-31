"""orchestrator/section_answer.py: one call per section, checked replies."""
import json
from types import SimpleNamespace

from career_agent.browser.form_model import Field
from career_agent.orchestrator.mapper import FillDecision


def test_one_call_per_section_and_only_real_options(monkeypatch):
    import career_agent.orchestrator.section_answer as S
    monkeypatch.setattr(S, "_facts", lambda conn, p: "SAVED ANSWERS:\n- Are you a citizen? -> India")
    calls = []

    def llm(prompt):
        calls.append(prompt)
        return json.dumps({"#cit": {"value": "Indian Citizen", "from": "citizenship"},
                           "#age": {"value": "25-30", "from": "invented"},          # not an option: dropped
                           "#ctc": {"value": None}})
    cit = Field("#cit", "combobox", "Are you an Indian citizen or OCI holder?", True, ["Indian Citizen", "OCI Holder"],
                section="Application Questions")
    age = Field("#age", "combobox", "Please select your age category", True, ["Under 16", "18 and Over"],
                section="Application Questions")
    ctc = Field("#ctc", "text", "Expected CTC", True, section="Application Questions")
    gender = Field("#g", "combobox", "Gender", True, ["Male", "Female"], section="Voluntary Disclosures")
    done = [FillDecision("#n", "text", "Name", "Rakshit", "fill", "qbank")]
    out, left = S.answer_sections([cit, age, ctc, gender], [cit, age, ctc, gender], done, {"job": {}}, llm, None, "")
    assert len(calls) == 1                                        # one section; the sensitive one never sent
    assert "Gender" not in calls[0].split("NOW ANSWER ONLY THIS SECTION")[1].split("ALREADY ANSWERED")[0]
    assert [(d.ref, d.value) for d in out] == [("#cit", "Indian Citizen")]
    assert {f.ref for f in left} == {"#age", "#ctc", "#g"}


def test_review_reads_the_whole_section_and_fixes_what_the_bank_matched_alone(monkeypatch):
    """Live 2026-10-31: Address Line 2/3 got line 1's address; a job's Location got the home address."""
    import career_agent.orchestrator.section_answer as S
    monkeypatch.setattr(S, "_facts", lambda conn, p: "")
    home = "3108, C wing, Chandak 34 Park estate, Goregaon West, Mumbai, 400104"
    f = lambda ref, label, sec, row=-1: Field(ref, "text", label, False, section=sec, row=row)   # noqa: E731
    a1, a2, a3 = f("#a1", "Address Line 1", "Address"), f("#a2", "Address Line 2", "Address"), f("#a3", "Address Line 3", "Address")
    em, em2 = f("#e", "Email", "Contact"), f("#e2", "Confirm your email", "Contact")
    loc = f("#loc", "Location", "Work Experience", 0)
    decs = [FillDecision("#a1", "text", "Address Line 1", home, "fill", "qbank"),
            FillDecision("#a2", "text", "Address Line 2", home, "fill", "qbank"),
            FillDecision("#a3", "text", "Address Line 3", home, "fill", "qbank"),
            FillDecision("#e", "text", "Email", "me@example.com", "fill", "qbank"),
            FillDecision("#e2", "text", "Confirm your email", "me@example.com", "fill", "qbank"),
            FillDecision("#loc", "text", "Location", home, "fill", "qbank_likely")]
    asked = []

    def llm(prompt):
        asked.append(prompt)
        if "THIS SECTION: [Address]" in prompt:
            return json.dumps({"#a2": {"verdict": "clear", "why": "repeats line 1"}, "#a3": {"verdict": "clear"}})
        return json.dumps({"#loc": {"verdict": "change", "value": "Mumbai, India", "why": "the job's city"}})
    fields = [a1, a2, a3, em, em2, loc]
    out, cleared = S.review_sections(fields, decs, {"job": {}}, llm, None, "")
    got = {d.ref: d.value for d in out}
    assert got["#a1"] == home and "#a2" not in got and "#a3" not in got          # the repeats go, line 1 stays
    assert got["#loc"] == "Mumbai, India" and got["#e2"] == "me@example.com"     # the confirm box may repeat
    assert len(asked) == 2 and not any("THIS SECTION: [Contact]" in p for p in asked)          # nothing in Contact needed a look
    assert cleared == []                                                         # optional boxes: left blank
