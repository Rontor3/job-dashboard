import sqlite3

from career_agent.longform.kb import Chunk, KnowledgeBase, split_sections
from career_agent.memory import qbank
from tests.longform.conftest import FIXTURE  # noqa: F401  (path only)


def test_split_sections_known_headings_and_unknown_fall_into_body():
    got = split_sections("intro text\n## problem\nA\n## Hardest\nB\n## misc\nC")
    assert got == {"body": "intro text\nC", "problem": "A", "hardest": "B"}
    assert split_sections("") == {}


def test_projects_are_only_project_units(kb):
    assert [u["id"] for u in kb.projects()] == ["p-churn", "p-ocr", "p-graph", "p-portfolio"]


def test_cards_are_one_chunk_per_project(kb):
    cards = kb.list_projects()
    assert [c.id for c in cards] == ["card:p-churn", "card:p-ocr", "card:p-graph", "card:p-portfolio"]
    assert all(c.kind == "card" and len(c.text) <= 400 for c in cards)
    assert "Neo4j" in kb.card("p-graph").text and kb.card("nope") is None


def test_get_project_returns_story_sections_then_verbatim_source(kb):
    ids = [c.id for c in kb.get_project("p-graph")]
    assert ids == ["project:p-graph:problem", "project:p-graph:hardest", "project:p-graph:result", "source:p-graph"]
    assert [c.id for c in kb.get_project("p-graph", ("hardest",))] == ["project:p-graph:hardest", "source:p-graph"]
    assert [c.id for c in kb.get_project("p-ocr")] == ["source:p-ocr"]          # no story written yet
    assert kb.get_project("nope") == []


def test_stories_and_facts_and_skills(kb):
    assert kb.get_story("story_looking_for").id == "story:story_looking_for"
    assert kb.get_story("missing") is None
    assert "story_how_you_work" in kb.story_slots()
    assert [c.id for c in kb.get_facts(("current_title", "nope"))] == ["fact:current_title"]
    assert kb.skills_chunk().text == "Skills: Python, SQL, PyTorch, AWS, Docker"


def test_rank_projects_by_overlap_with_the_text(kb):
    assert kb.rank_projects("graph neural networks to detect fraud rings")[0][0] == "p-graph"
    assert kb.rank_projects("OCR and document vision")[0][0] == "p-ocr"
    assert kb.rank_projects("unrelated words")[0][1] == 0


def test_load_reads_story_slots_and_project_stories_from_the_bank():
    conn = sqlite3.connect(":memory:")
    qbank.ensure(conn)
    for eid, ans in (("story_looking_for", "ML at scale"), ("story_project_p-graph", "## result\nFound rings"),
                     ("story_empty", "")):
        qbank.upsert_entry(conn, {"id": eid, "question": eid, "topic": "story", "atype": "text"})
        if ans:
            qbank.set_answer(conn, eid, ans)
    from tests.longform.conftest import FIXTURE as path
    loaded = KnowledgeBase.load(conn, path, {"years_experience": "3"})
    assert loaded.story_slots() == ["story_looking_for"]
    assert [c.id for c in loaded.get_project("p-graph")][0] == "project:p-graph:result"
    assert [c.id for c in loaded.get_facts(("years_experience",))] == ["fact:years_experience"]
