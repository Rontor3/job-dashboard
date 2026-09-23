"""Tests for MemoryRouter — dispatches the 4 ops to the right vaults.

Uses real ChromaDB, real FTS5, and a minimal inline profile.
"""
import json
import pytest
from pathlib import Path

from career_agent.memory.exact_tech import ExactTechVault
from career_agent.memory.semantic_behavior import SemanticBehaviorVault
from career_agent.routers.memory_router import MemoryRouter, memory_access


PROFILE = {
    "personal": {"name": "Rakshit Singh", "email": "rakshit@example.com"},
    "skills": {"languages": ["Python", "SQL"], "tools": ["AWS", "Docker"]},
}


@pytest.fixture()
def ingredients_path(tmp_path) -> Path:
    data = {
        "version": 1,
        "units": [
            {
                "id": "proj-fraud",
                "type": "project",
                "title": "Health Fraud Pipeline",
                "org": "Acme",
                "tech": "AWS Lambda Python",
                "tags": ["fraud", "ML", "AWS"],
                "source": "Health Fraud Pipeline — verbatim source text here.",
            }
        ],
    }
    p = tmp_path / "ingredients.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture()
def router(ingredients_path, tmp_path):
    # Use a per-test persistent dir so ChromaDB state doesn't bleed between tests
    return MemoryRouter(
        profile=PROFILE,
        exact_tech=ExactTechVault(ingredients_path),
        semantic=SemanticBehaviorVault(persist_dir=str(tmp_path / "chroma")),
    )


# ── GET_PROFILE_CHUNK ──────────────────────────────────────────────────────────

def test_get_profile_chunk_returns_section(router):
    result = memory_access("GET_PROFILE_CHUNK", {"section": "personal"}, router=router)
    assert result == {"personal": PROFILE["personal"]}


def test_get_profile_chunk_missing_section_raises(router):
    with pytest.raises(KeyError, match="section 'missing'"):
        memory_access("GET_PROFILE_CHUNK", {"section": "missing"}, router=router)


# ── EXACT_TECH_SEARCH ──────────────────────────────────────────────────────────

def test_exact_tech_search_returns_verbatim_source(router):
    results = memory_access("EXACT_TECH_SEARCH", {"keywords": "fraud AWS"}, router=router)
    assert results, "expected at least one hit"
    assert results[0]["source"] == "Health Fraud Pipeline — verbatim source text here."


def test_exact_tech_search_no_match(router):
    results = memory_access("EXACT_TECH_SEARCH", {"keywords": "xyzzy nonsense"}, router=router)
    assert results == []


# ── SEMANTIC_MATCH ─────────────────────────────────────────────────────────────

def test_semantic_match_empty_returns_none(router):
    result = memory_access("SEMANTIC_MATCH", {"question": "Why this company?"}, router=router)
    assert result is None


def test_semantic_match_after_record(router):
    memory_access(
        "RECORD_FEEDBACK",
        {"question": "Why this company?", "answer": "Great ML culture.", "event": "approve"},
        router=router,
    )
    result = memory_access("SEMANTIC_MATCH", {"question": "What draws you to this role?"}, router=router)
    assert result is not None
    assert result["answer"] == "Great ML culture."


# ── RECORD_FEEDBACK ────────────────────────────────────────────────────────────

def test_record_feedback_approve_increments(router):
    q = "Describe a technical challenge you solved"
    a = "Designed graph ML pipeline for fraud rings."
    memory_access("RECORD_FEEDBACK", {"question": q, "answer": a, "event": "approve"}, router=router)
    meta = memory_access("RECORD_FEEDBACK", {"question": q, "answer": a, "event": "approve"}, router=router)
    assert meta["approved_count"] == 2


def test_record_feedback_edit_resets(router):
    q = "What's your biggest weakness?"
    memory_access("RECORD_FEEDBACK", {"question": q, "answer": "Old answer", "event": "approve"}, router=router)
    meta = memory_access("RECORD_FEEDBACK", {"question": q, "answer": "New answer", "event": "edit"}, router=router)
    assert meta["confidence"] == 0.0
    assert meta["answer"] == "New answer"


# ── DUAL-WRITE ─────────────────────────────────────────────────────────────────

def test_record_feedback_dual_write_to_answer_memory(ingredients_path, tmp_path):
    """When answer_memory is wired, RECORD_FEEDBACK also writes to FTS5 fast-path."""
    import sqlite3
    from career_agent.memory.learned_answers import AnswerMemory, ensure

    conn = sqlite3.connect(":memory:")
    ensure(conn)
    am = AnswerMemory(conn)
    r = MemoryRouter(
        profile=PROFILE,
        exact_tech=ExactTechVault(ingredients_path),
        semantic=SemanticBehaviorVault(persist_dir=str(tmp_path / "chroma")),
        answer_memory=am,
    )
    memory_access(
        "RECORD_FEEDBACK",
        {"question": "Tell me about yourself", "answer": "ML engineer with 3 years.", "event": "approve"},
        router=r,
    )
    rows = conn.execute("SELECT answer FROM learned_answers").fetchall()
    answers = [row[0] for row in rows]
    assert any("ML engineer" in a for a in answers), f"dual-write missing from FTS5; got: {answers}"


# ── INVALID OP ─────────────────────────────────────────────────────────────────

def test_invalid_op_raises(router):
    with pytest.raises(ValueError, match="unknown op"):
        memory_access("DO_MAGIC", {}, router=router)
