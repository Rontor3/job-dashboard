import sqlite3
from types import SimpleNamespace

import pytest

from career_agent.browser.form_model import Field
from career_agent.memory.learned_answers import _norm, ensure
from career_agent.memory.qbank_memory import QBankMemory
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
    conn = sqlite3.connect(":memory:")
    ensure(conn)
    for label, answer, purpose in [("How many years of Python experience do you have?", "4", "years_experience"),
                                   ("Are you legally authorized to work in India?", "Yes", None)]:
        conn.execute("INSERT INTO learned_answers (qkey, label, answer, purpose, updated_at) VALUES (?,?,?,?,'2026-01-01')",
                     (_norm(label), label, answer, purpose))
        conn.execute("INSERT INTO learned_answers_fts (label, qkey) VALUES (?,?)", (_norm(label), _norm(label)))
    return SimpleNamespace(conn=conn)


@pytest.mark.parametrize("kind,field", [("purpose", _f("Total experience", "years_experience")),
                                        ("label_exact", _f("Are you legally authorized to work in India?")),
                                        ("fts_fuzzy", _f("Are you legally authorized to work in India or Nepal?")),
                                        ("none", _f("Favourite colour")),
                                        ("none", _f("Why us?", kind="textarea")),
                                        ("none", _f("I agree", "attestation"))])
def test_explain_reports_the_learned_tier_that_matched(mem, kind, field):
    assert explain(mem.conn, None, field)["retrieval_kind"] == kind


@pytest.mark.parametrize("label", ["Notice period", "LinkedIn profile URL", "Favourite colour", "Why us?"])
def test_qbank_explain_agrees_with_recall(qbank_conn, fake_embed, label):
    """Drift guard: the trace names an entry exactly when QBankMemory.recall
    fills the field, and that entry holds the answer it filled."""
    from career_agent.memory import qbank
    bank = QBankMemory(qbank_conn, embed=fake_embed)
    field = _f(label)
    got = bank.explain(field)
    decisions, _ = bank.recall([field])
    assert bool(decisions) == (got["candidates_json"] != [] and any(c["accepted"] for c in got["candidates_json"]))
    if decisions:
        assert qbank.get_entry(qbank_conn, got["retrieved_qkey"])["answer"] == decisions[0].value


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
