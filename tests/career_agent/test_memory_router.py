"""Tests for MemoryRouter — dispatches the 4 ops to the right vaults.

Uses real FTS5, a recording fake for the semantic vault, and a minimal inline profile.
"""
import json
import pytest
from pathlib import Path

from career_agent.memory.exact_tech import ExactTechVault
from career_agent.routers.memory_router import MemoryRouter, memory_access


PROFILE = {
    "personal": {"name": "Rakshit Singh", "email": "rakshit@example.com"},
    "skills": {"languages": ["Python", "SQL"], "tools": ["AWS", "Docker"]},
}


class FakeSemantic:
    def __init__(self):
        self.recorded = []

    def record_feedback(self, question, answer, event):
        self.recorded.append((question, answer, event))
        return {"answer": answer, "approved_count": 1}

    def semantic_match(self, question):
        for q, a, _ in reversed(self.recorded):
            if q == question:
                return {"answer": a, "question": q}
        return None


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
def semantic():
    return FakeSemantic()


@pytest.fixture()
def router(ingredients_path, semantic):
    return MemoryRouter(
        profile=PROFILE,
        exact_tech=ExactTechVault(ingredients_path),
        semantic=semantic,
    )


# ── GET_PROFILE_CHUNK ──────────────────────────────────────────────────────────

def test_get_profile_chunk_returns_section(router):
    result = memory_access("GET_PROFILE_CHUNK", {"section": "personal"}, router=router)
    assert result == {"personal": PROFILE["personal"]}


# ── EXACT_TECH_SEARCH ──────────────────────────────────────────────────────────

def test_exact_tech_search_returns_verbatim_source(router):
    results = memory_access("EXACT_TECH_SEARCH", {"keywords": "fraud AWS"}, router=router)
    assert results, "expected at least one hit"
    assert results[0]["source"] == "Health Fraud Pipeline — verbatim source text here."


# ── SEMANTIC_MATCH / RECORD_FEEDBACK ───────────────────────────────────────────

def test_record_feedback_goes_to_the_semantic_vault_and_semantic_match_reads_it(router, semantic):
    meta = memory_access(
        "RECORD_FEEDBACK",
        {"question": "Why this company?", "answer": "Great ML culture.", "event": "approve"},
        router=router,
    )
    assert semantic.recorded == [("Why this company?", "Great ML culture.", "approve")]
    assert meta == {"answer": "Great ML culture.", "approved_count": 1}
    result = memory_access("SEMANTIC_MATCH", {"question": "Why this company?"}, router=router)
    assert result["answer"] == "Great ML culture."


# ── DUAL-WRITE ─────────────────────────────────────────────────────────────────

def test_record_feedback_dual_write_to_answer_memory(ingredients_path, semantic):
    """When answer_memory is wired, RECORD_FEEDBACK also writes to the fast path, with its purpose."""
    written = []

    class AnswerMemory:
        def record(self, field, answer):
            written.append((field.label, field.purpose, answer))

    r = MemoryRouter(
        profile=PROFILE,
        exact_tech=ExactTechVault(ingredients_path),
        semantic=semantic,
        answer_memory=AnswerMemory(),
    )
    memory_access(
        "RECORD_FEEDBACK",
        {"question": "Notice period in days", "answer": "30", "event": "approve", "purpose": "notice_period"},
        router=r,
    )
    assert written == [("Notice period in days", "notice_period", "30")]


# ── INVALID OP ─────────────────────────────────────────────────────────────────

def test_invalid_op_raises(router):
    with pytest.raises(ValueError, match="unknown op"):
        memory_access("DO_MAGIC", {}, router=router)
