import json
import sqlite3
from types import SimpleNamespace as NS

from career_agent.browser.form_model import Field
from career_agent.browser.perception import to_form_model
from career_agent.longform.limits import field_limit
from career_agent.longform.pipeline import make_longform


def F(label="Q", description="", max_length=0):
    return Field("#q", "textarea", label, False, description=description, max_length=max_length)


def test_raw_row_max_length_reaches_the_field():
    row = {"ref": "#a", "kind": "textarea", "label": "Why?"}
    assert to_form_model([{**row, "max_length": 500}])[0].max_length == 500
    assert to_form_model([row])[0].max_length == 0


def test_field_dict_round_trip_keeps_max_length():
    import dataclasses
    f = F(max_length=7)
    assert Field(**dataclasses.asdict(f)).max_length == 7


def test_field_limit():
    assert field_limit(F("Say it (max 500 characters)", max_length=300)) == 300   # the attribute wins
    assert field_limit(F("Why us? (max 500 characters)")) == 500
    assert field_limit(F("Why us?", "up to 200 words")) == 1200
    assert field_limit(F("In 3 words")) == 18
    assert field_limit(F("Why us?")) is None
    assert field_limit(None) is None


def test_the_hook_trims_to_the_field_maxlength():
    from career_agent.memory import qbank
    from job_dashboard import qa_store
    from tests.longform.conftest import FIXTURE
    conn = sqlite3.connect(":memory:")
    qbank.ensure(conn)
    qa_store.ensure(conn)
    long = "First sentence. " + "Second sentence is rather long. " * 5

    def llm(p):
        return json.dumps({"needs": ["looking_for"]}) if "Allowed needs" in p else \
            json.dumps({"answer": long, "confidence": 90, "basis": "story"})
    run = make_longform(conn, {"title": "", "company": "", "description": ""}, {}, llm, None, FIXTURE)
    out = run("What are you looking for?", F(max_length=40))
    assert len(out["answer"]) <= 40 and "trimmed_to_limit" in out["flags"]
    assert isinstance(run.kb, __import__("career_agent.longform.kb", fromlist=["KnowledgeBase"]).KnowledgeBase)
