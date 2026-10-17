"""Insight endpoints: rewrite saves nothing; Accept files the lesson where it removes the cause; rules are listed,
turned off, and show their reach."""
import json

import pytest
from fastapi.testclient import TestClient

from career_agent.memory import qbank
from career_agent.orchestrator.rewrite import Engines
from job_dashboard import qa_store
from job_dashboard.api.app import create_app
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing


@pytest.fixture
def env(tmp_path, fake_embed):
    db = str(tmp_path / "t.db")
    c = init_db(db)
    insert_job(c, JobListing(source="s", title="DS", company="Twilio", location="Pune, India", job_url="https://x/1",
                             description="jd"))
    qbank.ensure(c)
    qa_store.record(c, job_id=1, run_key="r", ref="#ack", label="Acknowledge", kind="checkbox", status="needs_answer")
    qa_store.record(c, job_id=1, run_key="r", ref="#q", label="Why do you want this hypothetical?", kind="textarea",
                    status="filled", source="judgment", answer="ClaimGuard...")
    c.close()
    reply = {"lever": "policy", "value": "Yes", "concept": "acknowledging a privacy notice",
             "rule": "When asked to acknowledge a privacy notice, tick it", "applies_to": "similar"}
    eng = lambda conn, row: Engines(llm=lambda p: json.dumps(reply), embed=fake_embed)      # noqa: E731
    return TestClient(create_app(db_path=db, qa_embed=fake_embed, queue_launch=lambda *a: 0, insight_engines=eng)), db


def test_rewrite_saves_nothing_and_accept_files_a_default(env):
    c, db = env
    r = c.post("/api/application-qa/1/rewrite", json={"notes": ["always acknowledge privacy notices"]}).json()
    assert r["answer"] == "Yes" and r["directive"]["lever"] == "policy"
    assert c.get("/api/lessons").json()["lessons"] == []
    filed = c.post("/api/lessons", json={"proposal": r["proposal"], "answer": r["answer"]}).json()
    assert filed["filed_in"].startswith("new answer")
    assert qbank.exact(init_db(db), "Acknowledge") is not None
    [lesson] = c.get("/api/lessons").json()["lessons"]
    assert lesson["status"] == "filed" and lesson["lever"] == "policy"


def test_a_rule_can_be_turned_off_and_shows_its_reach(env):
    c, _ = env
    p = {"lever": "guide", "label": "Why do you want this hypothetical?", "concept": "why hypothetical",
         "rule": "never invent metrics", "applies_to": "long", "kind": "textarea"}
    lid = c.post("/api/lessons", json={"proposal": p, "answer": "x"}).json()["lesson_id"]
    assert c.put(f"/api/lessons/{lid}", json={"status": "off"}).json()["status"] == "off"
    assert c.put(f"/api/lessons/{lid}", json={"status": "deleted"}).status_code == 422
    reach = c.post("/api/lessons/reach", json={"concept": "x", "applies_to": "long", "label": "y", "kind": "textarea"}).json()
    assert reach["count"] == 1 and reach["examples"][0]["label"].startswith("Why do you want")


def test_bad_requests(env):
    c, _ = env
    assert c.post("/api/application-qa/99/rewrite", json={"notes": ["x"]}).status_code == 404
    assert c.post("/api/application-qa/1/rewrite", json={"notes": ["  "]}).status_code == 422
    assert c.post("/api/lessons", json={"proposal": {"lever": "hack", "label": "x"}}).status_code == 422
