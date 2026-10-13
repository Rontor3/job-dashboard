import json

from career_agent.longform.segments import answer_segmented, join, segment

JOB = {"title": "AI Engineer", "company": "Acme", "description": "We build agents."}


def llm_by_task(**answers):
    """Answer by which task the prompt is; a value may be a list consumed in order."""
    calls = {k: 0 for k in answers}

    def llm(prompt):
        for key, val in answers.items():
            if key in prompt:
                if isinstance(val, list):
                    i = min(calls[key], len(val) - 1)
                    calls[key] += 1
                    return val[i]
                return val
        return "GAP"
    return llm


def test_a_pure_hypothetical_is_one_general_piece_without_asking_the_model():
    segs = segment("3. Suppose an agent must remember a business for 6 months. How would you design its memory?", lambda p: 1 / 0)
    assert segs == [{"part": "Suppose an agent must remember a business for 6 months. How would you design its memory?", "source": "GENERAL"}]


def test_an_experience_question_is_split_by_the_model_and_one_piece_per_source():
    plan = json.dumps({"segments": [{"part": "a real evaluation", "source": "CANDIDATE"},
                                    {"part": "the metric used", "source": "CANDIDATE"},
                                    {"part": "the standard method", "source": "GENERAL"}]})
    segs = segment("How have you evaluated an LLM system? Give a metric.", lambda p: plan)
    assert [s["source"] for s in segs] == ["CANDIDATE", "GENERAL"] and "the metric used" in segs[0]["part"]


def test_a_candidate_part_with_no_support_is_held_and_never_invented(kb):
    plan = json.dumps({"segments": [{"part": "a real OCR project", "source": "CANDIDATE"}]})
    llm = llm_by_task(**{"Split this job-application question": plan, "WRITE ONLY THIS PART": "GAP"})
    out = answer_segmented("Describe a time you built an OCR system.", job=JOB, kb=kb, llm=llm)
    assert out["answer"] is None and out["confidence"] is None and any(f.startswith("gap:") for f in out["flags"])


def test_the_fact_check_rejects_an_overclaim_and_the_stricter_retry_is_used(kb):
    plan = json.dumps({"segments": [{"part": "a real OCR project", "source": "CANDIDATE"}]})
    llm = llm_by_task(**{"Split this job-application question": plan,
                         "WRITE ONLY THIS PART": ["I built OCR with a 500-case test set.", "Closest example from my work: OCR scoring of claim documents."],
                         "strict fact checker": ["NO invented test set", "YES"]})
    out = answer_segmented("Describe a time you built an OCR system.", job=JOB, kb=kb, llm=llm)
    assert out["answer"].startswith("Closest example from my work:") and "500-case" not in out["answer"] and out["confidence"] == 85


def test_join_keeps_the_order_asked_and_prints_the_closest_example_marker_once():
    parts = [({"source": "GENERAL"}, "I would build a golden set."),
             ({"source": "CANDIDATE"}, "Closest example from my work: I scored claim documents with OCR."),
             ({"source": "CANDIDATE"}, "Closest example from my work: Deployment used Docker on an internal server.")]
    text = join(parts)
    assert text.count("Closest example from my work:") == 1
    assert text.index("golden set") < text.index("OCR") < text.index("Docker")


def test_each_explicit_sub_ask_gets_its_own_piece_in_the_order_asked(kb):
    from career_agent.longform.segments import sub_asks
    q = "Describe a product you shipped, what happened after launch, and how one measures it."
    asks = json.dumps({"items": [{"item": "the product", "kind": "own", "quote": "Describe a product you shipped"},
                                 {"item": "what happened after launch", "kind": "own", "quote": "what happened after launch"},
                                 {"item": "how to measure it", "kind": "general", "quote": "how one measures it"},
                                 {"item": "an invented extra", "kind": "general", "quote": "integrate with a CRM"}]})
    got = sub_asks(q, lambda p: asks)
    assert [a["part"] for a in got] == ["the product", "what happened after launch", "how to measure it"]   # the invented ask is dropped
    assert [a["source"] for a in got] == ["CANDIDATE", "CANDIDATE", "GENERAL"]
    hyp = sub_asks("How would you design memory for an agent, and what could go wrong?", lambda p: json.dumps({"items": [
        {"item": "the design", "kind": "own", "quote": "How would you design memory"}]}))
    assert {a["source"] for a in hyp} == {"GENERAL"}                          # a hypothetical is never CANDIDATE


def test_an_invented_link_is_caught_but_a_known_or_quoted_one_is_not():
    from career_agent.longform.segments import invented_links
    from career_agent.longform.kb import Chunk
    chunks = [Chunk("c", "passage", "Code is at https://github.com/Rontor3/claimguard", "p")]
    assert invented_links("See https://github.com/tata-aig/graph-ml-fraud-rings", chunks, ["github.com/Rontor3"]) == ["github.com/tata-aig/graph-ml-fraud-rings"]
    assert invented_links("See https://github.com/Rontor3/claimguard", chunks) == []
    assert invented_links("My profile is github.com/Rontor3", [], ["https://github.com/Rontor3"]) == []


def test_a_follow_up_without_its_parent_question_is_held_not_answered(kb):
    out = answer_segmented("If Yes, what is the experience is about:", job=JOB, kb=kb, llm=lambda p: 1 / 0)
    assert out["answer"] is None and out["flags"] == ["follow_up_without_parent"]


def test_a_piece_the_coverage_check_finds_unanswered_is_rewritten(kb):
    asks = json.dumps({"items": [{"item": "what you built", "kind": "own", "quote": "what you built"},
                                 {"item": "how it was measured", "kind": "general", "quote": "how it was measured"}]})
    llm = llm_by_task(**{"List each separate thing": asks,
                         "strict fact checker": "YES",
                         "WRITE ONLY THIS PART: what you built": "I built OCR scoring.",
                         "WRITE ONLY THIS PART: how it was measured": ["It was good.", "I would measure it with a labelled test set."],
                         "decide whether the ANSWER addresses": [json.dumps({"judgments": [{"n": 1, "addressed": True}, {"n": 2, "addressed": False}]})]})
    out = answer_segmented("Tell me what you built and how it was measured, have you?", job=JOB, kb=kb, llm=llm)
    assert "labelled test set" in out["answer"] and "It was good." not in out["answer"]


def test_join_drops_a_sentence_that_repeats_an_earlier_one():
    text = join([({"source": "CANDIDATE"}, "I used a Pydantic SafeModel to validate output at the schema boundary."),
                 ({"source": "CANDIDATE"}, "I used a custom Pydantic SafeModel to validate the output at the schema boundary. It held out the latest quarter.")])
    assert text.count("Pydantic") == 1 and "latest quarter" in text
    general = join([({"source": "GENERAL"}, "I would cut latency with smaller models, caching and parallel tool calls."),
                    ({"source": "GENERAL"}, "I would cut cost with smaller models, caching and parallel tool calls.")])
    assert "latency" in general and "cost" in general                      # two different general points both stay


def test_every_personal_piece_of_one_answer_draws_on_one_project():
    from career_agent.longform.kb import KnowledgeBase
    long_graph = "Graph entity resolution over account graphs. We detect fraud rings with community detection on a heterogeneous graph. " * 2
    long_ocr = "Document OCR scoring pipeline for medical claims. We extract fields from scanned pages and score fraud risk. " * 2
    units = [{"id": "p-graph", "type": "project", "title": "Graph", "tech": ["neo4j"], "tags": ["graph"], "source": long_graph},
             {"id": "p-ocr", "type": "project", "title": "OCR", "tech": ["tesseract"], "tags": ["ocr"], "source": long_ocr}]
    kb = KnowledgeBase(units)
    assert kb.main_project("graph community detection fraud rings") == "p-graph"
    got = kb.passages("fraud rings scanned pages graph ocr", 8, project_id="p-graph")
    assert got and {c.project_id for c in got} == {"p-graph"}
