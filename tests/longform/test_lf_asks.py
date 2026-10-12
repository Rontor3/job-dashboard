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


def test_copied_run_finds_a_borrowed_phrase():
    from career_agent.longform.outreach import copied_run
    jd = "We are building the future of geospatial mapping with AI-powered LiDAR feature extraction for engineers"
    assert copied_run("I love that you are building the future of geospatial mapping with AI-powered tools", [jd])
    assert copied_run("Mach9 turns LiDAR scans into CAD deliverables, which is close to my work", [jd]) is None


def test_a_note_to_the_team_uses_company_research_not_a_stock_opening():
    # live WAAS 2026-10-12: 9/9 notes opened "I enjoy turning vague business requirements..." (an ingredient note)
    from types import SimpleNamespace as NS
    from career_agent.longform.kb import Chunk
    seen = []

    def llm(prompt):
        seen.append(prompt)
        return ("I enjoy turning vague business requirements into precise designs." if len(seen) == 1 else
                "Digital Surveyor turning LiDAR scans into CAD caught my eye. I built a document parser at Tata AIG.")

    class FakeCorpus:
        items = [Chunk("p1", "passage", "Built a document parser for claims", project_id="u1")]
        kb = NS(card=lambda pid: None)

        def search(self, *a, **k):
            return self.items

    research = NS(facts=[NS(text="Mach9 makes Digital Surveyor, turning LiDAR scans into CAD.", source_url="https://x")])
    out = answer_asks("Start a conversation with the team at Mach9. Share something about you.",
                      job={"company": "Mach9", "title": "ML Engineer"}, kb=None, corpus=FakeCorpus(), llm=llm,
                      research=lambda: research)
    assert "Digital Surveyor" in seen[0] and "Built a document parser" in seen[0]
    assert out["answer"].startswith("Digital Surveyor") and "rewrote_copied_phrase" in out["notes"]
