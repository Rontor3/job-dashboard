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


def test_rank_projects_reads_the_source_text_and_favours_rare_words(kb):
    assert kb.rank_projects("community detection")[0][0] == "p-graph"            # only in p-graph's verbatim source
    assert kb.rank_projects("who deployed the claim scoring")[0][0] == "p-ocr"   # rare "scoring"/"claim" beat a generic word
    assert kb.rank_projects("Monte Carlo simulation of weights")[0][0] == "p-portfolio"


def test_the_question_ranks_and_the_job_description_only_breaks_ties(kb):
    jd = "ocr document vision scoring " * 200                                   # a long description about OCR
    assert kb.rank_projects("graph neural networks", jd)[0][0] == "p-graph"       # the question wins over a loud description
    tied = kb.rank_projects("zzz unrelated words", "monte carlo etf weights")
    assert tied[0][0] == "p-portfolio" and tied[0][1] <= 0.11                      # the description only nudges, at a tenth


def test_embedding_similarity_adds_meaning_to_word_matching(kb):
    import numpy as np
    ids = [u["id"] for u in kb.projects()]
    vec = {i: np.eye(len(ids))[n] for n, i in enumerate(ids)}
    def embed(texts):                                                             # a unit's text -> its own axis; the query -> the OCR axis
        return np.array([vec["p-ocr"] if "xyzzy" in t else next((vec[i] for i, u in kb.units.items() if u.get("title", "") and u["title"] in t), vec["p-churn"]) for t in texts])
    kb.embed = embed
    ranked = kb.rank_projects("xyzzy zero shared words")                           # no word overlap at all; only meaning can rank
    assert ranked[0][0] == "p-ocr" and ranked[0][1] > 0


def test_industry_practice_is_ranked_for_the_question_and_labelled_as_general(kb):
    q = "How would you design the memory system for an agent that remembers a business across 6 months of conversations?"
    top = kb.practice_chunks(q)
    assert top and top[0].id == "practice:agent_memory" and top[0].kind == "practice"
    assert kb.practice_chunks("zzz qqq xxx unrelated gibberish") == []


def test_an_approach_question_gets_practice_plus_a_project_example(kb):
    from career_agent.longform.needs import Plan
    from career_agent.longform.recipes import retrieve
    q = "How have you evaluated whether an LLM or RAG system improved? Give a metric or test set."
    chunks = retrieve(Plan(("approach",), "p-ocr"), kb, question=q)
    kinds = [c.kind for c in chunks]
    assert "practice" in kinds and any(c.project_id == "p-ocr" for c in chunks)
