import json

from career_agent.longform.kb import Chunk
from career_agent.longform.verify import distinct_terms, fit_length, leak_check
from career_agent.longform.write import build_prompt, draft

JOB = {"title": "ML Engineer", "company": "Acme", "description": "fraud detection"}
CHUNKS = [Chunk("story:story_looking_for", "story_slot", "I want hard ML problems."),
          Chunk("project:p-graph:result", "project_story", "Found 40 rings.", "p-graph", "result"),
          Chunk("source:p-graph", "source", "Graph Entity Resolution - GNN community detection.", "p-graph")]


def test_prompt_labels_chunks_forbids_blending_and_states_the_limit():
    p = build_prompt("Why us?", CHUNKS, JOB, limit=300, avoid=("Churn Prediction Service",))
    assert "[CANDIDATE'S OWN WORDS]" in p and "[PROJECT STORY · p-graph]" in p and "[RÉSUMÉ TEXT (verbatim) · p-graph]" in p
    assert "Found 40 rings." in p and "under 300 characters" in p and "Do not mention: Churn Prediction Service" in p
    assert "separate" in p.lower() and '"confidence"' in p


def test_draft_parses_the_models_json_and_survives_failure():
    ok = draft("q", CHUNKS, JOB, lambda p: json.dumps({"answer": "Hello", "confidence": 88, "basis": "story"}))
    assert (ok["answer"], ok["confidence"], ok["basis"]) == ("Hello", 88, "story") and "prompt" in ok

    def boom(p): raise TimeoutError
    assert draft("q", CHUNKS, JOB, boom)["answer"] is None
    assert draft("q", CHUNKS, JOB, lambda p: "")["answer"] is None


def test_draft_parsed_true_for_valid_json():
    result = draft("q", CHUNKS, JOB, lambda p: json.dumps({"answer": "Hello", "confidence": 88, "basis": "story"}))
    assert result["parsed"] is True
    assert result["answer"] == "Hello"
    assert result["confidence"] == 88
    assert result["basis"] == "story"


def test_draft_parsed_false_for_prose():
    result = draft("q", CHUNKS, JOB, lambda p: "Sure! I would say I love fraud detection.")
    assert result["answer"] == "Sure! I would say I love fraud detection."
    assert result["confidence"] is None
    assert result["basis"] is None
    assert result["parsed"] is False


def test_draft_parsed_false_for_empty_or_error():
    result_empty = draft("q", CHUNKS, JOB, lambda p: "")
    assert result_empty["answer"] is None
    assert result_empty["parsed"] is False

    def boom(p): raise TimeoutError
    result_error = draft("q", CHUNKS, JOB, boom)
    assert result_error["answer"] is None
    assert result_error["parsed"] is False


def test_distinct_terms_are_unique_to_the_project(kb):
    graph = distinct_terms(kb, "p-graph")
    assert {"neo4j", "gnn", "graph entity resolution", "fraud"} <= graph and "ml" not in graph
    assert "docker" in distinct_terms(kb, "p-churn") and "pytorch" in distinct_terms(kb, "p-ocr")


def test_leak_check_flags_only_projects_that_were_not_retrieved(kb):
    used = [Chunk("source:p-churn", "source", "x", "p-churn")]
    assert leak_check("I used XGBoost and FastAPI.", used, kb) == []
    assert leak_check("I also built a GNN on Neo4j.", used, kb) == ["p-graph"]
    everyone = [Chunk(f"card:{p}", "card", "x", p) for p in ("p-churn", "p-ocr", "p-graph", "p-portfolio")]
    assert leak_check("GNN, Neo4j, OCR, Monte-Carlo", everyone, kb) == []     # an overview may mention all of them


def test_fit_length_trims_at_a_sentence_boundary():
    assert fit_length("Short.", 100) == ("Short.", False)
    assert fit_length("Short.", None) == ("Short.", False)
    text, trimmed = fit_length("First sentence. Second sentence is longer. Third.", 40)
    assert trimmed and text == "First sentence." and len(text) <= 40
    text, trimmed = fit_length("x" * 100, 30)
    assert trimmed and len(text) == 30
