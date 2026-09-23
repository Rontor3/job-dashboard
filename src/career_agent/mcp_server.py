"""Career agent MCP server — the 'doing' boundary.

Three tools expose the three routers to any MCP-capable orchestrator
(Claude Code, an external script, etc.):

  browser_action(action, payload)  — drive the live Playwright browser
  memory_access(op, args)          — tri-partite memory (profile / exact / semantic)
  human_loop_call(kind, payload)   — Telegram collect / approve

Run as stdio MCP server:
  PYTHONPATH=src python3 -m career_agent.mcp_server

Apply.py calls set_session() after the Playwright page is ready so
browser_action has a live page. memory_access and human_loop_call work
without a page (they only need memory_router and human_loop).
"""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("career-agent")

# Module-level session — apply.py calls set_session() before running the graph.
_session: dict | None = None


def set_session(
    *,
    page=None,
    deps=None,
    memory_router=None,
    human_loop=None,
    profile: dict | None = None,
) -> None:
    global _session
    _session = dict(
        page=page,
        deps=deps,
        memory_router=memory_router,
        human_loop=human_loop,
        profile=profile,
    )


def _require(need_page: bool = False) -> dict:
    if _session is None:
        raise RuntimeError(
            "No active session — call career_agent.mcp_server.set_session() first"
        )
    if need_page and _session.get("page") is None:
        raise RuntimeError(
            "browser_action requires a live Playwright page; "
            "start apply.py first so it registers the page via set_session()"
        )
    return _session


# ---------------------------------------------------------------------------
# Tool: browser_action
# ---------------------------------------------------------------------------

@mcp.tool()
def browser_action(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Drive the live Playwright browser.

    action:
      NAVIGATE  — goto url; payload: {url}
      PARSE     — snapshot form; returns list of fields
      CLICK     — click a button/link; payload: {label} or {ref}
      TYPE      — fill a field; payload: {ref, value}
      SELECT    — pick a select option; payload: {ref, value}
      UPLOAD    — set file input; payload: {ref, path}
      SCREENSHOT — take a screenshot; payload: {path?}
      PROBE     — classify captcha/gate; returns {gate: str}
      FILL      — apply a list of FillDecision dicts; payload: {decisions: [...]}
    """
    s = _require(need_page=True)
    page = s["page"]
    deps = s["deps"]

    if action == "NAVIGATE":
        page.goto(payload["url"], wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        return {"url": page.url}

    if action == "PARSE":
        fields = deps.snapshot(page)
        import dataclasses
        return {"fields": [dataclasses.asdict(f) for f in fields]}

    if action == "CLICK":
        label = payload.get("label", "")
        ref = payload.get("ref", "")
        if ref:
            page.locator(ref).first.click(timeout=5000)
        else:
            deps.click(page, label)
        page.wait_for_timeout(800)
        return {"clicked": ref or label}

    if action == "TYPE":
        page.fill(payload["ref"], str(payload["value"]))
        return {"filled": payload["ref"]}

    if action == "SELECT":
        page.select_option(payload["ref"], payload["value"])
        return {"selected": payload["value"]}

    if action == "UPLOAD":
        page.locator(payload["ref"]).set_input_files(payload["path"])
        return {"uploaded": payload["path"]}

    if action == "SCREENSHOT":
        path = payload.get("path", "/tmp/career_agent_shot.png")
        page.screenshot(path=path, full_page=True)
        return {"path": path}

    if action == "PROBE":
        return {"gate": deps.gate(page)}

    if action == "FILL":
        from .browser.form_model import FillDecision
        decs = [FillDecision(**d) for d in payload.get("decisions", [])]
        deps.fill(page, decs)
        return {"filled": len(decs)}

    raise ValueError(f"Unknown browser action: {action!r}")


# ---------------------------------------------------------------------------
# Tool: memory_access
# ---------------------------------------------------------------------------

@mcp.tool()
def memory_access(op: str, args: dict[str, Any]) -> Any:
    """Tri-partite memory operations.

    op:
      GET_PROFILE_CHUNK(section)     — static profile JSON slice
      EXACT_TECH_SEARCH(keywords)    — FTS5 verbatim source from ingredients.json
      SEMANTIC_MATCH(question)       — ChromaDB vector match + confidence
      RECORD_FEEDBACK(question, answer, event, purpose?)
                                     — event = "approve" | "edit"
    """
    s = _require()
    router = s.get("memory_router")
    if router is None:
        raise RuntimeError("No memory_router in session")
    return router.dispatch(op, args)


# ---------------------------------------------------------------------------
# Tool: human_loop_call
# ---------------------------------------------------------------------------

@mcp.tool()
def human_loop_call(kind: str, payload: dict[str, Any]) -> Any:
    """Telegram human-loop: send a card or collect field answers.

    kind:
      approve — send approval card; payload: {card: str}; returns bool
      collect — collect field answers; payload: {fields: [{ref, label, kind, ...}]}
                returns {ref: value}
    """
    s = _require()
    human = s.get("human_loop")
    if human is None:
        raise RuntimeError("No human_loop in session")

    if kind == "approve":
        return {"approved": human.approve(payload.get("card", ""))}

    if kind == "collect":
        from .browser.form_model import Field
        fields = [Field(**f) for f in payload.get("fields", [])]
        return human.collect(fields)

    raise ValueError(f"Unknown human_loop kind: {kind!r}")


if __name__ == "__main__":
    mcp.run()
