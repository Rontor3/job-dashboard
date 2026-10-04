"""The retrieval tools as one dispatcher, so the MCP server (and any other caller) shares the pipeline's code."""
from __future__ import annotations


def _out(chunks) -> list[dict]:
    return [{"id": c.id, "kind": c.kind, "text": c.text,
             "project_id": c.project_id, "section": c.section} for c in chunks if c is not None]


def knowledge_dispatch(kb, op, args) -> list[dict]:
    args = args or {}
    if op == "LIST_PROJECTS":
        return _out(kb.list_projects())
    if op == "GET_PROJECT":
        if not args.get("project_id"):
            raise ValueError("GET_PROJECT needs project_id")
        return _out(kb.get_project(args["project_id"], tuple(args["sections"]) if args.get("sections") else None))
    if op == "GET_STORY":
        return _out([kb.get_story(args.get("slot", ""))])
    if op == "GET_FACTS":
        return _out(kb.get_facts(tuple(args.get("keys", ()))))
    if op == "GET_COMPANY_CONTEXT":
        from .recipes import Ctx, _company
        return _out(_company(Ctx(company_text=args.get("company_text") or "", jd_text=args.get("jd_text") or "")))
    raise ValueError(f"unknown op {op!r}; expected LIST_PROJECTS, GET_PROJECT, GET_STORY, GET_FACTS or GET_COMPANY_CONTEXT")
