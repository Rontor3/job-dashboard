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
    assert {"neo4j", "gnn", "graph entity resolution"} <= graph and "ml" not in graph
    assert "fraud" not in graph          # a tag is a generic word, not evidence of another project
    assert "docker" in distinct_terms(kb, "p-churn") and "pytorch" in distinct_terms(kb, "p-ocr")


def test_leak_check_flags_only_projects_that_were_not_retrieved(kb):
    used = [Chunk("source:p-churn", "source", "x", "p-churn")]
    assert leak_check("I used XGBoost and FastAPI.", used, kb) == []
    assert leak_check("I also built a GNN on Neo4j.", used, kb) == ["p-graph"]
    everyone = [Chunk(f"card:{p}", "card", "x", p) for p in ("p-churn", "p-ocr", "p-graph", "p-portfolio")]
    assert leak_check("GNN, Neo4j, OCR, Monte-Carlo", everyone, kb) == []     # an overview may mention all of them


def test_a_term_in_the_retrieved_text_is_not_a_leak(kb):
    pool = [Chunk("skills:pool", "fact", "Skills: Python, SQL, PyTorch, AWS, Docker")]
    assert leak_check("I use Docker and PyTorch daily.", pool, kb) == []
    used = [Chunk("source:p-churn", "source", "x", "p-churn")]
    assert leak_check("I also built a GNN on Neo4j.", used, kb) == ["p-graph"]


def test_fit_length_trims_at_a_sentence_boundary():
    assert fit_length("Short.", 100) == ("Short.", False)
    assert fit_length("Short.", None) == ("Short.", False)
    text, trimmed = fit_length("First sentence. Second sentence is longer. Third.", 40)
    assert trimmed and text == "First sentence." and len(text) <= 40
    text, trimmed = fit_length("x" * 100, 30)
    assert trimmed and len(text) == 30


def test_a_hypothetical_prompt_tells_the_writer_to_plan_and_cite_an_example_only_if_it_applies():
    from career_agent.longform.write import build_prompt
    from career_agent.longform.kb import Chunk
    chunks = [Chunk("source:p-ocr", "source", "OCR scoring pipeline.", "p-ocr")]
    hyp = build_prompt("How would you design X?", chunks, {"title": "t", "company": "c"}, hypothetical=True)
    assert "INDUSTRY PRACTICE" in hyp and "ONE sentence" in hyp and "never restate" in hyp.lower()
    assert "HYPOTHETICAL" not in build_prompt("Describe a project", chunks, {"title": "t", "company": "c"})


def test_the_writer_is_told_not_to_bend_a_project_to_fit_and_to_flag_low_confidence():
    from career_agent.longform.write import build_prompt
    from career_agent.longform.kb import Chunk
    p = build_prompt("q", [Chunk("source:p", "source", "text", "p")], {"title": "t", "company": "c"})
    assert "do NOT bend a project to fit" in p and "confidence below 40" in p


def test_a_project_name_that_is_not_in_the_material_is_caught():
    from career_agent.longform.verify import invented_projects
    from career_agent.longform.kb import Chunk
    chunks = [Chunk("source:p", "source", "ClaimGuard scores claim documents with Claude Vision.", "p")]
    assert invented_projects("For example, in the 'Customer Support Chatbot' project, I did X.", chunks) == ["Customer Support Chatbot"]
    assert invented_projects("In the EVA project I measured task success.", chunks) == ["EVA"]
    assert invented_projects("In the ClaimGuard project I validated outputs.", chunks) == []
    assert invented_projects("I would store facts per tenant.", chunks) == []
