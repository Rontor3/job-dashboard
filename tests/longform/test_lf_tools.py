import pytest

from career_agent.longform.tools import knowledge_dispatch


def test_list_projects_and_get_project(kb):
    cards = knowledge_dispatch(kb, "LIST_PROJECTS", {})
    assert [c["id"] for c in cards] == ["card:p-churn", "card:p-ocr", "card:p-graph", "card:p-portfolio"]
    got = knowledge_dispatch(kb, "GET_PROJECT", {"project_id": "p-graph", "sections": ["hardest"]})
    assert [c["id"] for c in got] == ["project:p-graph:hardest", "source:p-graph"]
    assert set(got[0]) == {"id", "kind", "text"}


def test_story_and_facts(kb):
    assert knowledge_dispatch(kb, "GET_STORY", {"slot": "story_looking_for"})[0]["kind"] == "story_slot"
    assert knowledge_dispatch(kb, "GET_STORY", {"slot": "nope"}) == []
    assert [c["id"] for c in knowledge_dispatch(kb, "GET_FACTS", {"keys": ["current_title", "nope"]})] == ["fact:current_title"]


def test_unknown_ops_and_missing_args_are_clear_errors(kb):
    with pytest.raises(ValueError, match="unknown op"):
        knowledge_dispatch(kb, "DELETE_EVERYTHING", {})
    with pytest.raises(ValueError, match="project_id"):
        knowledge_dispatch(kb, "GET_PROJECT", {})


def test_the_mcp_tool_uses_the_session_knowledge(kb):
    pytest.importorskip("mcp")                                # the MCP package is optional in some environments
    from career_agent import mcp_server
    mcp_server.set_session(knowledge=kb)
    got = mcp_server.knowledge_access("LIST_PROJECTS", {})
    assert len(got) == 4
    mcp_server.set_session()                                  # leave no session behind
    with pytest.raises(RuntimeError):
        mcp_server.knowledge_access("LIST_PROJECTS", {})
