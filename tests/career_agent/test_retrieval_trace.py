import sqlite3

import pytest

from career_agent.browser.form_model import Field
from career_agent.memory.learned_answers import AnswerMemory
from career_agent.memory.retrieval_trace import explain


def _f(label, purpose=None, kind="text"):
    return Field("#x", kind, label, False, [], None, purpose)


class FakeVault:
    def __init__(self, cands):
        self.cands = cands

    def candidates(self, q, n=3):
        return self.cands


@pytest.fixture
def mem():
    m = AnswerMemory(sqlite3.connect(":memory:"))
    m.record(_f("How many years of Python experience do you have?", "years_experience"), "4")
    m.record(_f("Are you legally authorized to work in India?"), "Yes")
    return m


CASES = [
    ("purpose", _f("Total experience", "years_experience")),
    ("label_exact", _f("Are you legally authorized to work in India?")),
    ("fts_fuzzy", _f("Are you legally authorized to work in India or Nepal?")),
    ("none", _f("Favourite colour")),
    ("none", _f("Why us?", kind="textarea")),            # essays are never recalled
    ("none", _f("I agree", "attestation")),
]


@pytest.mark.parametrize("kind,field", CASES)
def test_explain_agrees_with_recall(mem, kind, field):
    """Drift guard: the trace must say 'hit' exactly when AnswerMemory.recall
    fills the field, and name the entry that holds the answer it filled."""
    got = explain(mem.conn, None, field)
    decisions, _ = mem.recall([field])
    assert got["retrieval_kind"] == kind
    assert bool(decisions) == (kind != "none")
    if decisions:
        row = mem.conn.execute("SELECT answer FROM learned_answers WHERE qkey=?",
                               (got["retrieved_qkey"],)).fetchone()
        assert row[0] == decisions[0].value


def test_rejected_fuzzy_candidate_is_reported_but_not_a_hit(mem):
    got = explain(mem.conn, None, _f("Are you authorized to work in Canada for sponsorship reasons?"))
    assert got["retrieval_kind"] == "none"
    assert got["candidates_json"] and not got["candidates_json"][0]["accepted"]


def test_semantic_candidates_recorded_and_used_when_nothing_learned(mem):
    v = FakeVault([{"question": "Why do you want to join us?", "distance": 0.2, "confidence": 0.33, "accepted": True},
                   {"question": "Salary?", "distance": 0.9, "confidence": 0.0, "accepted": False}])
    got = explain(mem.conn, v, _f("Why us?", kind="textarea"))
    assert got["retrieval_kind"] == "semantic" and got["retrieved_qkey"] == "why do you want to join us"
    assert [c["accepted"] for c in got["candidates_json"]] == [True, False]


def test_explain_never_raises(mem):
    class Boom:
        def candidates(self, *a, **k): raise RuntimeError("chroma down")
    assert explain(mem.conn, Boom(), _f("Why us?"))["retrieval_kind"] == "none"
