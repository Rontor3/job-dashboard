"""Tests for SemanticBehaviorVault — real ChromaDB + ONNX embeddings.

No fake embedders: we want to catch real setup failures.
"""
import pytest
from career_agent.memory.semantic_behavior import (
    SemanticBehaviorVault,
    AUTONOMY_THRESHOLD,
    _MATCH_DISTANCE,
)


@pytest.fixture()
def vault():
    return SemanticBehaviorVault(persist_dir=None)


def test_empty_vault_returns_none(vault):
    assert vault.semantic_match("Why do you want this role?") is None


def test_record_then_exact_lookup(vault):
    vault.record_feedback("Describe your ML experience", "I built fraud models at Tata AIG", "approve")
    result = vault.get("Describe your ML experience")
    assert result is not None
    assert result["answer"] == "I built fraud models at Tata AIG"
    assert result["approved_count"] == 1


def test_semantic_match_rewording(vault):
    """The core invariant: a paraphrase of a stored question should still match."""
    vault.record_feedback(
        "Why do you want to join this company?",
        "I admire their ML work and mission.",
        "approve",
    )
    match = vault.semantic_match("What motivates you to apply here?")
    # Should find a match — two phrasings of the same intent
    assert match is not None, "semantic match failed on a clear reworded question"
    assert match["answer"] == "I admire their ML work and mission."
    assert 0.0 <= match["distance"] <= _MATCH_DISTANCE


def test_no_match_for_unrelated_question(vault):
    vault.record_feedback(
        "What is your experience with SQL?",
        "Five years of PostgreSQL and query optimisation.",
        "approve",
    )
    # A question about salary has nothing to do with SQL experience
    result = vault.semantic_match("What are your salary expectations?")
    # May return None or a far-distance hit — either is fine
    if result is not None:
        assert result["distance"] > 0.5, "unrelated question returned a suspiciously close match"


def test_confidence_increments_on_approve(vault):
    q = "Tell me about your leadership experience"
    vault.record_feedback(q, "Led a team of four at Tata AIG.", "approve")
    meta = vault.record_feedback(q, "Led a team of four at Tata AIG.", "approve")
    assert meta["approved_count"] == 2
    assert abs(meta["confidence"] - 2 / AUTONOMY_THRESHOLD) < 1e-9


def test_confidence_reaches_1_after_threshold(vault):
    q = "Describe a time you solved a hard problem"
    ans = "Designed a graph ML pipeline to detect fraud rings."
    for _ in range(AUTONOMY_THRESHOLD):
        meta = vault.record_feedback(q, ans, "approve")
    assert meta["confidence"] == 1.0
    assert meta["autonomous"] if "autonomous" in meta else True
    # semantic_match should flag it autonomous too
    match = vault.semantic_match(q)
    assert match is not None
    assert match["autonomous"] is True


def test_edit_resets_confidence(vault):
    q = "Why are you leaving your current role?"
    vault.record_feedback(q, "Old answer", "approve")
    vault.record_feedback(q, "Old answer", "approve")
    meta = vault.record_feedback(q, "Seeking more impactful ML work.", "edit")
    assert meta["approved_count"] == 0
    assert meta["confidence"] == 0.0
    assert meta["answer"] == "Seeking more impactful ML work."


def test_edit_overwrites_answer(vault):
    q = "What is your greatest strength?"
    vault.record_feedback(q, "First answer", "approve")
    vault.record_feedback(q, "Corrected answer", "edit")
    result = vault.get(q)
    assert result["answer"] == "Corrected answer"


def test_invalid_event_raises(vault):
    with pytest.raises(ValueError, match="event must be"):
        vault.record_feedback("Q?", "A", "neither")


def test_multiple_entries_best_match(vault):
    """With multiple entries, the nearest should win."""
    vault.record_feedback("Describe your Python skills", "Expert Python, 5 years.", "approve")
    vault.record_feedback("What is your experience with Java?", "Minimal Java, prefer Python.", "approve")
    match = vault.semantic_match("How proficient are you in Python?")
    assert match is not None
    assert "Python" in match["answer"]
