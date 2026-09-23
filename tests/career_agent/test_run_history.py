"""summarize_run() only reads checkpoints — it doesn't care what produced
them. So these tests write checkpoints with a tiny stand-in graph (no real
Playwright page needed) whose state fields match AgentState's channel names,
then read them back through the real build_graph()."""
import sqlite3
from typing import TypedDict

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import StateGraph, END

from career_agent.orchestrator.run_history import summarize_run


class _FakeState(TypedDict):
    steps: int
    kind: str
    cred_action: str | None
    stopped_reason: str | None
    pending_human: list
    gate_notice: dict | None


def _write_checkpoints(db_path, thread_id, node_updates):
    """Run a trivial linear graph whose nodes each return one of `node_updates`
    in order, so the checkpoint DB ends up with the same shape a real run
    would produce."""
    g = StateGraph(_FakeState)
    for i, update in enumerate(node_updates):
        g.add_node(f"n{i}", lambda state, config, u=update: u)
    g.set_entry_point("n0")
    for i in range(len(node_updates) - 1):
        g.add_edge(f"n{i}", f"n{i + 1}")
    g.add_edge(f"n{len(node_updates) - 1}", END)

    conn = sqlite3.connect(db_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    app = g.compile(checkpointer=checkpointer)
    app.invoke({"steps": 0, "kind": "", "cred_action": None, "stopped_reason": None,
                "pending_human": [], "gate_notice": None},
               {"configurable": {"thread_id": thread_id}})
    conn.close()


def test_summarize_run_empty_for_unknown_thread(tmp_path):
    db = str(tmp_path / "graph.db")
    sqlite3.connect(db).close()  # file must exist for SqliteSaver to open it
    assert summarize_run("no-such-thread", db) == []


def test_summarize_run_groups_by_step_keeping_latest(tmp_path):
    db = str(tmp_path / "graph.db")
    _write_checkpoints(db, "t1", [
        {"steps": 1, "kind": "form", "cred_action": None, "stopped_reason": None,
         "pending_human": [], "gate_notice": None},
        # same step (1) recorded twice, as perceive/fill/advance would within
        # one page -> only the later one should survive.
        {"steps": 1, "kind": "form", "cred_action": None, "stopped_reason": None,
         "pending_human": [{"ref": "why_us", "label": "Why us?"}], "gate_notice": None},
        {"steps": 2, "kind": "form", "cred_action": None, "stopped_reason": "stuck",
         "pending_human": [], "gate_notice": None},
    ])
    out = summarize_run("t1", db)
    assert [o["step"] for o in out] == [1, 2]
    assert out[0]["pending_human"] == [{"ref": "why_us", "label": "Why us?"}]
    assert out[1]["stopped_reason"] == "stuck"


def test_summarize_run_reports_login_wall_before_first_fill(tmp_path):
    db = str(tmp_path / "graph.db")
    _write_checkpoints(db, "t2", [
        {"steps": 0, "kind": "password", "cred_action": "register",
         "stopped_reason": None, "pending_human": [], "gate_notice": None},
        {"steps": 1, "kind": "form", "cred_action": "register",
         "stopped_reason": None, "pending_human": [], "gate_notice": None},
    ])
    out = summarize_run("t2", db)
    assert out[0] == {"step": 0, "kind": "password", "cred_action": "register",
                       "stopped_reason": None, "pending_human": [],
                       "gate_notice": None, "screenshot": None}


def test_summarize_run_resolves_existing_screenshot(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "perceive1.png").write_bytes(b"fake-png")
    db = str(tmp_path / "graph.db")
    _write_checkpoints(db, "t3", [
        {"steps": 1, "kind": "form", "cred_action": None, "stopped_reason": None,
         "pending_human": [], "gate_notice": None},
    ])
    out = summarize_run("t3", db, run_dir=str(run_dir))
    assert out[0]["screenshot"] == str(run_dir / "perceive1.png")


def test_summarize_run_missing_screenshot_is_none(tmp_path):
    db = str(tmp_path / "graph.db")
    _write_checkpoints(db, "t4", [
        {"steps": 1, "kind": "form", "cred_action": None, "stopped_reason": None,
         "pending_human": [], "gate_notice": None},
    ])
    out = summarize_run("t4", db, run_dir=str(tmp_path / "nonexistent"))
    assert out[0]["screenshot"] is None
