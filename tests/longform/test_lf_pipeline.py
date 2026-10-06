import json
import sqlite3
from types import SimpleNamespace as NS

from career_agent import longform
from career_agent.longform.pipeline import answer_longform, make_longform, prior_project
from career_agent import longform as _lf  # noqa: F401
from job_dashboard import qa_store

JOB = {"id": 7, "title": "ML Engineer", "company": "Acme", "description": "graph neural networks to detect fraud rings"}


def scripted(plan, answers):
    """A fake model: first call = the plan, later calls = drafts (consumed in order)."""
    replies = iter(answers)

    def llm(prompt):
        return json.dumps(plan) if "Allowed needs" in prompt else next(replies)
    return llm


def reply(text, conf=90):
    return json.dumps({"answer": text, "confidence": conf, "basis": "story"})


def test_end_to_end_one_project_answer_records_how_it_was_built(kb):
    llm = scripted({"needs": ["one_project"], "project_id": "p-graph"}, [reply("I found 40 fraud rings with a graph model.")])
    out = answer_longform("Describe a project you are proud of", job=JOB, kb=kb, llm=llm)
    assert out["answer"].startswith("I found 40") and out["confidence"] == 90 and out["flags"] == []
    assert out["needs"] == ["one_project"] and out["project_id"] == "p-graph"
    assert out["used"][-1] == "source:p-graph" and not any("churn" in u for u in out["used"])
    assert "Found 40 rings in the first month." in out["prompt"] and "Docker" not in out["prompt"]   # other projects are not in the prompt


def test_a_leaked_project_is_redrafted_once_then_flagged(kb):
    llm = scripted({"needs": ["one_project"], "project_id": "p-graph"},
                   [reply("I built a GNN, and also a XGBoost churn model."), reply("I built a GNN and used Neo4j.")])
    clean = answer_longform("Describe a project", job=JOB, kb=kb, llm=llm)
    assert "XGBoost" not in clean["answer"] and clean["flags"] == []

    llm = scripted({"needs": ["one_project"], "project_id": "p-graph"},
                   [reply("GNN plus XGBoost."), reply("Still GNN plus XGBoost.")])
    flagged = answer_longform("Describe a project", job=JOB, kb=kb, llm=llm)
    assert flagged["flags"] == ["project_leak:p-churn"]
    assert flagged["confidence"] is None and clean["confidence"] == 90      # a leak holds the answer back


def test_length_limit_is_enforced_and_flagged(kb):
    llm = scripted({"needs": ["looking_for"]}, [reply("First sentence. " + "Second sentence is rather long. " * 5)])
    out = answer_longform("What are you looking for?", job=JOB, kb=kb, llm=llm, limit=40)
    assert len(out["answer"]) <= 40 and out["flags"] == ["trimmed_to_limit"]


def test_a_failing_model_falls_back_to_a_general_answer_and_never_raises(kb):
    def boom(p): raise TimeoutError
    out = answer_longform("Tell me about yourself", job=JOB, kb=kb, llm=boom)
    assert out["answer"] and "general_fallback" in out["flags"] and out["needs"] == ["intro"]


def test_company_claims_not_in_the_material_are_reported(kb):
    llm = scripted({"needs": ["why_company"], "project_id": "p-graph"},
                   [reply("Acme's $2B Series C and its Phoenix platform excite me.")])
    out = answer_longform("Why do you want to join us?", job=JOB, kb=kb, llm=llm, research=None)
    assert isinstance(out["unsupported_company_claims"], list)


def test_prose_reply_is_kept_but_flagged_unparsed(kb):
    llm = scripted({"needs": ["one_project"], "project_id": "p-graph"}, ["I love fraud detection."])
    out = answer_longform("Describe a project", job=JOB, kb=kb, llm=llm)
    assert out["answer"] == "I love fraud detection." and "unparsed_reply" in out["flags"]


def test_prior_project_is_read_from_the_recorded_draft():
    conn = sqlite3.connect(":memory:")
    qa_store.ensure(conn)
    assert prior_project(conn, 7, "Describe a project") is None
    qa_store.record(conn, job_id=7, run_key="r", ref="x", label="Describe a project", kind="textarea", status="filled",
                    context_json={"project_id": "p-ocr", "needs": ["one_project"]})
    assert prior_project(conn, 7, "Describe a project") == "p-ocr"
    assert prior_project(conn, 8, "Describe a project") is None


def test_make_longform_loads_once_and_reuses_the_prior_choice(tmp_path, kb):
    from career_agent.memory import qbank
    from tests.longform.conftest import FIXTURE
    conn = sqlite3.connect(":memory:")
    qbank.ensure(conn)                                                   # KnowledgeBase.load reads the story entries
    qa_store.ensure(conn)
    qa_store.record(conn, job_id=7, run_key="r", ref="x", label="Describe a project", kind="textarea", status="filled",
                    context_json={"project_id": "p-ocr"})
    llm = scripted({"needs": ["one_project"], "project_id": "p-graph"}, [reply("About OCR scoring.")])
    run = make_longform(conn, JOB, {"years_experience": "3"}, llm, None, FIXTURE)
    out = run("Describe a project", NS(label="Describe a project"))
    assert out["project_id"] == "p-ocr"                                  # the user's earlier choice sticks


def test_sticky_choice_works_when_the_job_dict_has_no_id(kb):
    from career_agent.memory import qbank
    from tests.longform.conftest import FIXTURE
    conn = sqlite3.connect(":memory:")
    qbank.ensure(conn)
    qa_store.ensure(conn)
    qa_store.record(conn, job_id=7, run_key="r", ref="x", label="Describe a project", kind="textarea", status="filled",
                    context_json={"project_id": "p-ocr"})
    llm = scripted({"needs": ["one_project"], "project_id": "p-graph"}, [reply("About OCR scoring.")])
    job = {"title": "t", "company": "c", "description": "d"}               # what job_dashboard.db.get_job returns: no id
    run = make_longform(conn, job, {"years_experience": "3"}, llm, None, FIXTURE, job_id=7)
    assert run("Describe a project", NS(label="Describe a project"))["project_id"] == "p-ocr"


def test_the_hook_uses_the_job_it_is_passed(kb):
    from career_agent.memory import qbank
    from tests.longform.conftest import FIXTURE
    conn = sqlite3.connect(":memory:")
    qbank.ensure(conn)
    qa_store.ensure(conn)
    seen = []

    def llm(prompt):
        seen.append(prompt)
        return json.dumps({"needs": ["intro"]}) if "Allowed needs" in prompt else reply("Hi.")
    run = make_longform(conn, {"title": "", "company": "", "description": ""}, {}, llm, None, FIXTURE)
    run("Tell me about yourself", None, {"title": "Role", "company": "ZetaCorp", "description": "d"})
    assert any("ZetaCorp" in p for p in seen)


def test_prior_project_matches_the_normalized_question_and_needs_a_real_key():
    conn = sqlite3.connect(":memory:")
    qa_store.ensure(conn)
    qa_store.record(conn, job_id=7, run_key="r", ref="x", label="Describe a project", kind="textarea", status="filled",
                    context_json={"project_id": "p-ocr"})
    assert prior_project(conn, 7, "  Describe  a project *") == "p-ocr"
    qa_store.record(conn, job_id=7, run_key="r2", ref="y", label="Describe a project", kind="textarea", status="filled",
                    context_json={"prompt": "mentions project_id in the text", "needs": ["intro"]})
    assert prior_project(conn, 7, "Describe a project") == "p-ocr"


def test_the_result_carries_plan_provenance(kb):
    llm = scripted({"needs": ["looking_for"], "reason": "asks about goals"}, [reply("Hard ML problems.")])
    out = answer_longform("What are you looking for?", job=JOB, kb=kb, llm=llm)
    assert out["plan_source"] and "plan_reason" in out
