"""Insights beside a run's answers (career_agent/orchestrator/insight.py + rewrite.py, memory/lessons.py).

    POST /api/application-qa/{row}/rewrite   {notes: [str]} -> {answer, directive, proposal, trace, before}; saves nothing
    POST /api/lessons                        {proposal, answer} -> file it where it removes the cause
    GET  /api/lessons                        every lesson, newest first (rules, links, facts, superseded ones too)
    PUT  /api/lessons/{id}                   {rule?, applies_to?, status?: active|off}
    POST /api/lessons/reach                  {concept, applies_to, label, kind} -> past questions a rule would touch
    GET  /api/insight/backlog                open/unsure answers grouped by what they ask, biggest group first

Accepting the answer itself goes through PUT /api/application-qa/{id}/answer (save_as=once), like any edit.
The local model is started for a rewrite and stopped after it (it holds a lot of RAM); with the setting
insight_local_only=1 Claude is never used as the fallback.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from job_dashboard import qa_store
from job_dashboard.db import init_db


class RewriteBody(BaseModel):
    notes: list[str] = Field(min_length=1, max_length=8)


class FileBody(BaseModel):
    proposal: dict
    answer: Optional[str] = Field(default=None, max_length=8000)


class LessonPatch(BaseModel):
    rule: Optional[str] = Field(default=None, max_length=500)
    applies_to: Optional[str] = None
    status: Optional[str] = None


class ReachBody(BaseModel):
    concept: Optional[str] = Field(default=None, max_length=400)
    applies_to: str = "question"
    label: str = Field(default="", max_length=500)
    kind: str = "text"


def default_engines(db_path) -> Callable:
    """conn, row -> Engines with the real models: local first (Claude fallback unless insight_local_only), Haiku plans,
    and the essay writer for the row's job."""
    def make(conn, row):
        from career_agent.longform.pipeline import make_longform_or_none
        from career_agent.memory import facts, qbank
        from career_agent.orchestrator.claude_assist import with_claude_fallback
        from career_agent.orchestrator.rewrite import Engines, _contact, _job
        from job_dashboard.letter.draft import make_default_llm
        local = make_default_llm()
        llm = local if qa_store.get_setting(conn, "insight_local_only") == "1" else with_claude_fallback(local)
        job = {**_job(conn, row["job_id"]), "id": row["job_id"]}
        run = None
        if (row.get("kind") or "") == "textarea":
            run = make_longform_or_none(conn, job, _contact(conn), llm, None,
                                        str(Path(db_path).parent / "answer_style" / "ingredients.json"), row["job_id"])
        longform = (lambda q, steer: run(q, steer=steer)) if run else None
        return Engines(llm=llm, embed=qbank.default_embed, facts_llm=facts.claude_cli_llm("haiku"), longform=longform)
    return make


def build_insight_router(db_path, engines: Optional[Callable] = None, embed: Optional[Callable] = None,
                         manage_model: bool = True) -> APIRouter:
    router = APIRouter()
    engines = engines or default_engines(db_path)

    def db():
        from career_agent.memory import lessons, qbank
        conn = init_db(db_path)
        qa_store.ensure(conn)
        qbank.ensure(conn)
        lessons.ensure(conn)
        return conn

    def embedder():
        if embed is not None:
            return embed
        from career_agent.memory.qbank import default_embed
        return default_embed

    @router.post("/api/application-qa/{row_id}/rewrite")
    def rewrite_answer(row_id: int, body: RewriteBody):
        from career_agent.orchestrator.rewrite import load_row, rewrite
        notes = [n.strip()[:1000] for n in body.notes if n and n.strip()]
        if not notes:
            raise HTTPException(status_code=422, detail="write what is wrong first")
        conn = db()
        started = False
        try:
            row = load_row(conn, row_id)
            if row is None:
                raise HTTPException(status_code=404, detail="no such answer")
            if manage_model:
                from job_dashboard.apply import local_model
                started = local_model.ensure_running()
            try:
                return rewrite(conn, row_id, notes, engines(conn, row))
            except HTTPException:
                raise
            except Exception as e:                        # both models down, a broken lesson: say so, save nothing
                raise HTTPException(status_code=502, detail=f"couldn't rewrite it ({type(e).__name__}: {e})"[:300])
        finally:
            conn.close()
            if started:
                from job_dashboard.apply import local_model
                local_model.stop()

    @router.post("/api/lessons")
    def file_lesson(body: FileBody):
        from career_agent.memory import lessons
        p = body.proposal
        if p.get("lever") not in ("trust", "fact", "lookup", "policy", "derive", "shape", "identify", "scope", "guide") \
                or not p.get("label"):
            raise HTTPException(status_code=422, detail="not a rewrite proposal")
        conn = db()
        try:
            return lessons.file(conn, p, body.answer, embedder())
        finally:
            conn.close()

    @router.get("/api/lessons")
    def list_lessons():
        from career_agent.memory import lessons
        conn = db()
        try:
            return {"lessons": lessons.listing(conn)}
        finally:
            conn.close()

    @router.put("/api/lessons/{lesson_id}")
    def patch_lesson(lesson_id: int, body: LessonPatch):
        from career_agent.memory import lessons
        conn = db()
        try:
            try:
                ok = lessons.update(conn, lesson_id, **body.model_dump())
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))
            if not ok:
                raise HTTPException(status_code=404, detail="no such lesson")
            return next(x for x in lessons.listing(conn) if x["id"] == lesson_id)
        finally:
            conn.close()

    @router.post("/api/lessons/reach")
    def lesson_reach(body: ReachBody):
        from career_agent.memory import lessons
        if body.applies_to not in ("question", "similar", "long", "short"):
            raise HTTPException(status_code=422, detail="applies_to must be question, similar, long or short")
        conn = db()
        try:
            return lessons.reach(conn, body.concept or body.label, body.applies_to, body.label, body.kind, embedder())
        finally:
            conn.close()

    @router.get("/api/insight/backlog")
    def backlog(limit: int = 12):
        from career_agent.memory.backlog import groups
        conn = db()
        try:
            return {"groups": groups(conn, embedder(), max(1, min(limit, 50)))}
        finally:
            conn.close()

    return router
