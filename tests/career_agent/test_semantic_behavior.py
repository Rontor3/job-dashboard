"""Tests for SemanticBehaviorVault with a deterministic bag-of-words embedder and
a fresh on-disk Chroma store per test. The real ONNX model runs only in the
opt-in RUN_REAL_EMBEDDINGS=1 test."""
import os

import pytest
from career_agent.memory.semantic_behavior import SemanticBehaviorVault


@pytest.fixture()
def vault(tmp_path, fake_embed):
    return SemanticBehaviorVault(persist_dir=str(tmp_path / "chroma"), embed=fake_embed)


def test_empty_vault_returns_none(vault):
    assert vault.semantic_match("Why do you want this role?") is None


def test_record_then_exact_lookup(vault):
    vault.record_feedback("Describe your ML experience", "I built fraud models at Tata AIG", "approve")
    result = vault.get("Describe your ML experience")
    assert result is not None
    assert result["answer"] == "I built fraud models at Tata AIG"
    assert result["approved_count"] == 1


def test_vaults_do_not_share_state(tmp_path, fake_embed):
    a = SemanticBehaviorVault(persist_dir=str(tmp_path / "a"), embed=fake_embed)
    a.record_feedback("Why do you want this role?", "Mission.", "approve")
    b = SemanticBehaviorVault(persist_dir=str(tmp_path / "b"), embed=fake_embed)
    assert b.semantic_match("Why do you want this role?") is None


def test_no_match_for_unrelated_question(vault):
    vault.record_feedback("What is your experience with SQL?",
                          "Five years of PostgreSQL and query optimisation.", "approve")
    assert vault.semantic_match("Salary expectations per annum?") is None


def test_two_approvals_are_not_yet_autonomous(vault):
    q = "Tell me about your leadership experience"
    vault.record_feedback(q, "Led a team of four at Tata AIG.", "approve")
    meta = vault.record_feedback(q, "Led a team of four at Tata AIG.", "approve")
    assert meta["approved_count"] == 2
    assert abs(meta["confidence"] - 2 / 3) < 1e-9
    assert vault.semantic_match(q)["autonomous"] is False


def test_three_approvals_make_an_answer_autonomous(vault):
    q = "Describe a time you solved a hard problem"
    ans = "Designed a graph ML pipeline to detect fraud rings."
    for _ in range(3):
        meta = vault.record_feedback(q, ans, "approve")
    assert meta["confidence"] == 1.0
    match = vault.semantic_match(q)
    assert match is not None and match["autonomous"] is True and match["answer"] == ans


def test_edit_overwrites_answer_and_resets_confidence(vault):
    q = "Why are you leaving your current role?"
    vault.record_feedback(q, "Old answer", "approve")
    vault.record_feedback(q, "Old answer", "approve")
    meta = vault.record_feedback(q, "Seeking more impactful ML work.", "edit")
    assert meta["approved_count"] == 0
    assert meta["confidence"] == 0.0
    assert vault.get(q)["answer"] == "Seeking more impactful ML work."


def test_invalid_event_raises(vault):
    with pytest.raises(ValueError, match="event must be"):
        vault.record_feedback("Q?", "A", "neither")


def test_multiple_entries_best_match(vault):
    vault.record_feedback("Describe your Python skills", "Expert Python, 5 years.", "approve")
    vault.record_feedback("What is your experience with Java?", "Minimal Java, prefer Python.", "approve")
    match = vault.semantic_match("Describe your Python proficiency")
    assert match is not None and match["answer"] == "Expert Python, 5 years."


@pytest.mark.skipif(os.getenv("RUN_REAL_EMBEDDINGS") != "1", reason="set RUN_REAL_EMBEDDINGS=1 to run the ONNX model")
def test_real_model_matches_a_paraphrase(tmp_path):
    vault = SemanticBehaviorVault(persist_dir=str(tmp_path / "chroma"))
    vault.record_feedback("Why do you want to join this company?", "I admire their ML work and mission.", "approve")
    match = vault.semantic_match("What motivates you to apply here?")
    assert match is not None and match["answer"] == "I admire their ML work and mission."
