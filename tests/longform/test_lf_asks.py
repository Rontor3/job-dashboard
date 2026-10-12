import json

from career_agent.longform.asks import answer_asks, material_for
from career_agent.longform.corpus import Corpus

ASKS = {"items": [{"item": "a product you built", "quote": "a product you built", "kind": "own"},
                  {"item": "a link to it", "quote": "a link", "kind": "own"}]}


def fake_llm(answer):
    def llm(prompt):
        if "explicitly asks the applicant" in prompt:
            return json.dumps(ASKS)
        if "quote the sentence of the ANSWER" in prompt:
            return json.dumps({"answers": {"1": "x", "2": "x"}})        # every ask covered: no repair
        return answer
    return llm


def test_answers_are_capped_and_marked_fillable(kb):
    long = " ".join(f"I built part {i} of the Churn Prediction Service." for i in range(20))
    out = answer_asks("Describe a product you built and share a link.", job={}, kb=kb, corpus=Corpus(kb, {}),
                      llm=fake_llm(long), limit=120)
    assert out["answer"] and len(out["answer"]) <= 120 and "trimmed_to_limit" in out["notes"]
    assert out["confidence"] == 85 and out["flags"] == []          # a repair or trim is a note, never a flag


def test_a_made_up_link_is_never_filled(kb):
    out = answer_asks("Describe a product you built and share a link.", job={}, kb=kb, corpus=Corpus(kb, {}),
                      llm=fake_llm("See https://github.com/someone-else/churn for the code."))
    assert out["answer"] is None and out["confidence"] is None and out["flags"][0].startswith("invented_link")


def test_outcome_asks_bring_the_result_cards(kb):
    chunks = material_for({"part": "the result of the churn service", "source": "CANDIDATE"}, "Describe a product", kb,
                          Corpus(kb, {}))
    assert any(c.kind == "card" and "Impact" in c.text for c in chunks)
