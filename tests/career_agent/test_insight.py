"""Insight → cause → rewrite → filed where it removes the cause. Cases are the real gaps found in application_qa
(2026-10-17): consent defaults, a job-relative city question, a fact told twice, other wording, an essay that
dragged in a project."""
import json

import pytest

from career_agent.memory import lessons, qbank
from career_agent.orchestrator import insight
from career_agent.orchestrator.rewrite import Engines, rewrite
from job_dashboard import qa_store
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing
from tests.conftest import QBANK_ENTRIES


def reply(**d):
    return lambda prompt: json.dumps(d)


@pytest.fixture
def conn(tmp_path, fake_embed):
    c = init_db(str(tmp_path / "t.db"))
    insert_job(c, JobListing(source="s", title="Data Scientist", company="Twilio", location="Ahmedabad, Gujarat, India",
                             job_url="https://x/1", description="jd"))
    qbank.ensure(c)
    for e in QBANK_ENTRIES:
        qbank.upsert_entry(c, e)
        if e.get("answer"):
            qbank.set_answer(c, e["id"], e["answer"])
        for t in [e["question"], *e.get("wordings", [])]:
            qbank.add_wording(c, t, e["id"], fake_embed([t])[0], "seed")
    return c


def row(conn, label, kind="text", answer=None, source=None, status="needs_answer", options=None):
    qa_store.record(conn, job_id=1, run_key="r", ref=label, label=label, kind=kind, answer=answer, source=source,
                    status=status, **({"options_json": options} if options else {}))
    return conn.execute("SELECT max(id) FROM application_qa").fetchone()[0]


# ── reading the note ───────────────────────────────────────────────────────────────────────────────────────────

def test_the_model_never_sees_the_current_answer():
    seen = []
    insight.interpret({"label": "Current CTC", "kind": "text", "origin": "model"}, ["it's 25 LPA"],
                      {"company": "Acme"}, lambda p: seen.append(p) or "{}")
    assert "it's 25 LPA" in seen[0] and "22" not in seen[0]


def test_an_unreadable_reply_still_keeps_the_note_as_the_instruction():
    d = insight.interpret({"label": "Why us?"}, ["no greeting line"], {}, lambda p: "sorry, no json")
    assert d["lever"] == "guide" and d["rule"] == "no greeting line" and d["applies_to"] == "question"


def test_company_names_never_enter_a_lesson():
    d = insight.validate({"lever": "guide", "rule": "When Twilio asks why, keep it short", "concept": "why Twilio"},
                         ["x"], "Twilio")
    assert "Twilio" not in d["rule"] and "the employer" in d["concept"]


def test_a_value_lever_without_a_value_is_just_an_instruction():
    assert insight.validate({"lever": "fact"}, ["fix it"])["lever"] == "guide"


# ── rewrite (writes nothing) and filing ───────────────────────────────────────────────────────────────────────

def test_policy_acknowledge_default_is_filed_as_a_saved_answer_for_the_concept(conn, fake_embed):
    rid = row(conn, "Acknowledge", kind="checkbox")
    before = conn.execute("SELECT count(*) FROM qbank_entry").fetchone()[0]
    eng = Engines(llm=reply(lever="policy", value="Yes", concept="acknowledging a privacy or data-processing notice",
                            rule="When a form asks to acknowledge a privacy notice, tick it", applies_to="similar"),
                  embed=fake_embed)
    out = rewrite(conn, rid, ["always acknowledge privacy notices"], eng)
    assert out["answer"] == "Yes" and out["directive"]["lever"] == "policy"
    assert conn.execute("SELECT count(*) FROM qbank_entry").fetchone()[0] == before          # nothing written yet
    filed = lessons.file(conn, out["proposal"], out["answer"], fake_embed)
    assert filed["filed_in"].startswith("new answer")
    eid = qbank.exact(conn, "Acknowledge")
    assert qbank.get_entry(conn, eid)["answer"] == "Yes" and qbank.get_entry(conn, eid)["topic"] == "policy"


def test_lookup_links_other_wording_to_the_saved_answer(conn, fake_embed):
    rid = row(conn, "Days of notice you must serve")
    eng = Engines(llm=reply(lever="lookup", query="notice period in days", concept="notice period"), embed=fake_embed)
    out = rewrite(conn, rid, ["it's my notice period, check my answers"], eng)
    assert out["answer"] == "30" and out["proposal"]["entry_id"] == "notice_period"
    lessons.file(conn, out["proposal"], out["answer"], fake_embed)
    assert qbank.exact(conn, "Days of notice you must serve") == "notice_period"              # next run: exact hit


def test_a_corrected_fact_replaces_the_old_value_and_keeps_it_in_history(conn, fake_embed):
    rid = row(conn, "What is your notice period in days?", answer="30", source="qbank", status="filled")
    eng = Engines(llm=reply(lever="fact", value="60", concept="What is your notice period in days?"), embed=fake_embed)
    out = rewrite(conn, rid, ["my notice is 60 days now"], eng)
    lessons.file(conn, out["proposal"], out["answer"], fake_embed)
    assert qbank.get_entry(conn, "notice_period")["answer"] == "60"
    log = lessons.listing(conn)[0]
    assert log["before"] == {"entry": "notice_period", "answer": "30"} and log["status"] == "filed"


def test_trust_links_the_wording_to_the_answer_that_holds_that_value(conn, fake_embed):
    rid = row(conn, "Residential address line", answer="C-12, Sector 5, Noida 201301", source="qbank_likely")
    out = rewrite(conn, rid, ["this is right"], Engines(llm=reply(lever="trust"), embed=fake_embed))
    assert out["proposal"]["entry_id"] == "home_address"
    lessons.file(conn, out["proposal"], out["answer"], fake_embed)
    assert qbank.exact(conn, "Residential address line") == "home_address"


def test_derive_compares_the_job_with_the_applicant(conn, fake_embed):
    conn.execute("INSERT INTO application_profile (id, location) VALUES (1, 'Mumbai, India')")
    conn.commit()
    rid = row(conn, "Are you currently based in Ahmedabad, Gujarat?", kind="radio_group", options=["Yes", "No"])
    plan = {"plan": {"op": "cmp", "cmp": "==", "args": [{"fact": "location", "field": "city"},
                                                        {"fact": "job_location", "field": "city"}]}}
    eng = Engines(llm=lambda p: json.dumps({"lever": "derive", "concept": "living in the job's city",
                                            "rule": "When asked if I live in the job's city, compare it with mine",
                                            "applies_to": "similar"}) if "Causes" in p else
                  '{"value": "No", "card": "location"}',
                  embed=fake_embed, facts_llm=lambda p: json.dumps(plan))
    out = rewrite(conn, rid, ["use the location from the JD and compare it with mine"], eng)
    assert out["answer"] == "No", out["trace"]
    filed = lessons.file(conn, out["proposal"], out["answer"], fake_embed)
    assert filed["filed_in"] == "rule"
    hit = lessons.for_question(conn, "Are you currently based in the job's city?", "radio_group", fake_embed)
    assert hit and hit[0]["lever"] == "derive"


def test_essay_scope_reaches_the_essay_writer_as_a_steer(conn, fake_embed):
    rid = row(conn, "You inherit a production RAG agent with poor answer quality. What do you investigate first?",
              kind="textarea", answer="I would investigate the clinical reasoning layer...", source="judgment",
              status="filled")
    got = {}
    eng = Engines(llm=reply(lever="scope", concept="a hypothetical technical scenario",
                            rule="When a question is a hypothetical scenario, answer from general reasoning, not my projects",
                            applies_to="similar"),
                  embed=fake_embed, longform=lambda q, steer: got.update(steer) or {"answer": "First, precision of retrieval..."})
    out = rewrite(conn, rid, ["general context, my project does not belong here"], eng)
    assert got["scope"] == "general" and "general reasoning" in got["rule"]
    assert out["answer"].startswith("First")


# ── rules: conditional, superseded, never blanket ─────────────────────────────────────────────────────────────

def test_a_rule_fires_on_its_concept_only_and_a_newer_one_supersedes_it(conn, fake_embed):
    base = {"lever": "scope", "concept": "hypothetical technical scenario question", "rule": "general reasoning",
            "applies_to": "similar", "label": "x"}
    first = lessons.add(conn, base, fake_embed)
    assert lessons.for_question(conn, "a hypothetical technical scenario question about RAG", "textarea", fake_embed)
    assert not lessons.for_question(conn, "What is your notice period?", "text", fake_embed)
    lessons.add(conn, {**base, "rule": "general reasoning, two short paragraphs"}, fake_embed)
    status = {r["id"]: r["status"] for r in lessons.listing(conn)}
    assert status[first] == "superseded"


def test_reach_lists_the_past_questions_a_rule_would_touch(conn, fake_embed):
    row(conn, "Acknowledge", kind="checkbox")
    row(conn, "I acknowledge the privacy notice", kind="checkbox")
    row(conn, "Notice period", kind="text")
    r = lessons.reach(conn, "acknowledge privacy notice", "similar", "Acknowledge", "checkbox", fake_embed)
    labels = {e["label"] for e in r["examples"]}
    assert "I acknowledge the privacy notice" in labels and "Notice period" not in labels
    assert lessons.reach(conn, "x", "question", "Acknowledge", "checkbox", fake_embed)["count"] == 1


# ── the essay writer obeys a scope lesson, but an explicit ask wins ───────────────────────────────────────────

def test_scope_general_turns_project_material_into_general_reasoning_unless_the_ask_wants_own_work():
    from career_agent.longform.asks import _ruled, _steered
    asks = [{"part": "What would you investigate first in a RAG agent with poor answers?", "source": "CANDIDATE"},
            {"part": "Describe a project you built with retrieval", "source": "CANDIDATE"},
            {"part": "Why this company?", "source": "COMPANY"}]
    got = [a["source"] for a in _steered(asks, {"scope": "general"})]
    assert got == ["GENERAL", "CANDIDATE", "COMPANY"]
    assert _steered(asks, None) == asks
    p = _ruled("You write...\n\nAnswer:", {"rule": "- never invent metrics"})
    assert "never invent metrics" in p and p.endswith("\n\nAnswer:")


def test_a_shape_lesson_makes_the_next_run_answer_from_the_plan_with_that_instruction(conn, fake_embed):
    from types import SimpleNamespace
    from career_agent.memory.qbank_memory import QBankMemory
    lessons.add(conn, {"lever": "shape", "concept": "currency of expected compensation", "applies_to": "similar",
                       "rule": "When a box asks for the compensation currency, give only the currency", "label": "x"},
                fake_embed)
    conn.execute("INSERT INTO application_profile (id, salary_expectation) VALUES (1, '30 LPA')")
    conn.commit()
    seen = []
    mem = QBankMemory(conn, embed=fake_embed, contact={"salary_expectation": "30 LPA"},
                      llm=lambda p: '{"value": "INR", "card": "salary_expectation"}',
                      facts_llm=lambda p: seen.append(p) or '{"plan": {"fact": "salary_expectation", "field": "currency"}}')
    f = SimpleNamespace(ref="#cur", label="Expected compensation - Currency", kind="text", options=[], purpose=None,
                        description="", required=False, input_type="", autocomplete="")
    m, value = mem._answer(f)
    assert value == "INR" and "only the currency" in seen[0] and "lessons" in m.note
