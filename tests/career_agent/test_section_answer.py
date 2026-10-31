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
