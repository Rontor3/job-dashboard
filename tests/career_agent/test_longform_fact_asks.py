"""A plain fact about the applicant (referral, notice) is answered from saved answers, never padded with projects
(Lingaro 2026-11-01: 'Did a Consultant ... recommend you?' got three projects and then 'No')."""
from career_agent.longform.asks import build_prompt, material_for
from career_agent.longform.kb import KnowledgeBase


def test_a_fact_ask_takes_saved_answers_and_no_projects():
    import numpy as np

    def embed(texts):                  # a stand-in for meaning: referral words share one axis, notice another
        v = [[1.0, 0.0] if any(w in t.lower() for w in ("refer", "recommend")) else [0.0, 1.0] for t in texts]
        return np.asarray(v)
    kb = KnowledgeBase([{"id": "p1", "type": "project", "title": "Graph ML", "org": "Tata AIG"}], embed=embed,
                       saved=[("Were you referred by a current employee?", "No"), ("What is your notice period?", "30 days")])
    ask = {"part": "whether a consultant recommended you", "source": "FACT"}
    got = material_for(ask, "Did a Consultant from our Group recommended you to apply?", kb, corpus=None)
    assert "Saved answer — Were you referred by a current employee?: No" in [c.text for c in got]
    assert all(c.kind == "fact" for c in got)
    prompt = build_prompt("Did a Consultant recommend you?", [ask], [(ask, got)], kb=kb)
    assert "ASK 1 (FACT)" in prompt and "never add projects" in prompt and "Graph ML" not in prompt
