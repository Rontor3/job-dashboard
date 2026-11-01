"""A fact told about an essay is material for the rewrite and is filed on the project the answer is about
(2026-11-02: 'add 3x lift in rejection bucket and 5x lift in fraud, total saving 20 cr per year' became the whole
3-5 line answer and was to be saved as a stray standalone answer)."""
import json
import sqlite3

from career_agent.memory.lessons import add_project_fact
from career_agent.longform.asks import answer_asks
from career_agent.longform.kb import KnowledgeBase


def test_the_fact_lands_on_the_named_projects_impact(tmp_path):
    p = tmp_path / "ingredients.json"
    p.write_text(json.dumps({"units": [{"id": "fraud", "type": "project", "title": "Health Fraud Detection Pipeline",
                                         "impact": ["ROC > 0.85"]},
                                        {"id": "graph", "type": "project", "title": "Graph ML"}]}) + "\n")
    conn = sqlite3.connect(":memory:")
    pid = add_project_fact(conn, "3x lift in rejection bucket; 20 cr saving per year",
                           "I built the Health Fraud Detection Pipeline (Tata AIG) ...", path=p)
    assert pid == "fraud"
    assert json.loads(p.read_text())["units"][0]["impact"] == ["ROC > 0.85", "3x lift in rejection bucket; 20 cr saving per year"]
    assert add_project_fact(conn, "x", "no project named here", path=p) is None


def test_the_rewrite_gives_the_fact_to_the_writer_as_material():
    kb = KnowledgeBase([{"id": "fraud", "type": "project", "title": "Fraud", "org": "Tata AIG"}])
    seen = []

    def llm(prompt):
        seen.append(prompt)
        if "List each separate thing" in prompt:
            return json.dumps({"items": [{"item": "business result", "quote": "the business result", "kind": "own"}]})
        return "It saved 20 cr a year."

    class Corpus:
        items = []
        def search_multi(self, *a, **k): return []
        def scores(self, q): return []
    answer_asks("Describe the business result of a model you shipped", job={}, kb=kb, corpus=Corpus(), llm=llm,
                steer={"facts": ["total saving 20 cr per year"]})
    assert any("The applicant states: total saving 20 cr per year" in p for p in seen)
