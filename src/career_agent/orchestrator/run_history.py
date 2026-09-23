"""Read-only summary of a past LangGraph run, for the dashboard's "Last agent
run" view. The only place that touches LangGraph's checkpoint format —
callers get a plain list of dicts.

Relies on `apply.py`'s `_run_graph` now pointing its checkpointer at a durable
SqliteSaver (previously InMemorySaver, lost on process exit) instead of a
separate event log: the graph's own per-node state already carries steps,
page kind, credential action, and stop reason, so there's nothing new to
instrument — just something new to read.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def summarize_run(thread_id: str, db_path: str, run_dir: str | None = None) -> list[dict]:
    """Return one entry per distinct `steps` value reached during the run
    (oldest first), each the most complete state recorded at that step —
    including a stop that happened before the next fill (e.g. a gate hit
    while perceiving the page that would have been step N+1 still reports
    under step N, since `steps` only increments after a successful fill).

    Empty list means no checkpoint history exists for this thread (never run,
    or run before checkpoints were persisted).
    """
    from langgraph.checkpoint.sqlite import SqliteSaver
    from .graph import build_graph

    conn = sqlite3.connect(db_path, check_same_thread=False)
    try:
        checkpointer = SqliteSaver(conn)
        app = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": thread_id}}

        history = list(app.get_state_history(config))
    finally:
        conn.close()

    history.reverse()  # oldest -> newest; get_state_history yields newest-first

    by_step: dict[int, dict] = {}
    for snap in history:
        v = snap.values
        if not v or not v.get("kind"):
            # `not v`: the empty "__start__" placeholder checkpoint.
            # `not kind`: the initial-state checkpoint recorded before
            # classify_node has run — kind is "" there and only there,
            # since classify_node always sets a real value on its first write.
            continue
        steps = v.get("steps", 0)
        screenshot = None
        if run_dir:
            ss = Path(run_dir) / f"perceive{steps}.png"
            if ss.exists():
                screenshot = str(ss)
        by_step[steps] = {
            "step": steps,
            "kind": v.get("kind"),
            "cred_action": v.get("cred_action"),
            "stopped_reason": v.get("stopped_reason"),
            "pending_human": v.get("pending_human") or [],
            "gate_notice": v.get("gate_notice"),
            "screenshot": screenshot,
        }
    return [by_step[k] for k in sorted(by_step)]
