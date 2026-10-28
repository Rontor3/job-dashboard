"""The straggler retry's answers ride with the human's into human_gate, but they are the model's: recorded as
judgment, never as 'human' (which re-runs reuse first and the bank learns from). Wipro, live 2026-10-23: 'State =
Not provided in text' and 'Education Type = Bachelor's degree' were stored as your answers."""
from types import SimpleNamespace as NS

import career_agent.orchestrator.graph as graph
from career_agent.browser.form_model import Field
from career_agent.orchestrator import answering


def test_straggler_answers_are_not_recorded_as_yours(monkeypatch):
    fields = [Field("#st", "text", "State", True, [], None, None), Field("#ph", "text", "Phone", True, [], None, None)]
    monkeypatch.setattr(graph, "interrupt", lambda payload: {"#st": "Not provided in text", "#ph": "7565052330",
                                                             "__machine_refs__": ["#st"]})
    human, judged, filled = [], [], []
    qa = NS(answered=lambda f, a: human.append((f.ref, a)), decision=lambda d: judged.append((d.ref, d.source)))
    monkeypatch.setattr(answering, "record_answers",
                        lambda fs, ans, c: [human.append((f.ref, ans[f.ref])) for f in fs if f.ref in ans])
    deps = NS(fill=lambda page, ds: filled.extend(ds))
    state = {"pending_human": [graph._f2d(f) for f in fields], "decisions": []}
    graph.human_gate_node(state, {"configurable": {"page": None, "deps": deps, "qa": qa}})
    assert human == [("#ph", "7565052330")]                       # only the human's own answer
    assert judged == [("#st", "judgment")]
    assert {d.ref: d.source for d in filled} == {"#st": "judgment", "#ph": "human"}
