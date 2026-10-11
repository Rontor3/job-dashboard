"""Routes behind the in-app agent's apply tools (spec 2026-10-11-agent-driven-apply-design.md).

    GET  /api/apply-sessions/{job_id}            where the run stands (apply_run row + priority)
    POST /api/apply-sessions/{job_id}            apply_start: open the job (only a queued/running job)
    POST /api/apply-sessions/{job_id}/reach      get to the form
    GET  /api/apply-sessions/{job_id}/form       the page's fields with grounded suggestions
    POST /api/apply-sessions/{job_id}/fill       {answers:[{id, value, source, citation?}], accept_suggestions?}
    POST /api/apply-sessions/{job_id}/advance    Next / Continue (never the final control)
    POST /api/apply-sessions/{job_id}/submit     the final click, gated by autonomy.autosubmit_policy + priority
    POST /api/apply-sessions/{job_id}/pause      {reason, detail, questions:[{id, why}]}
    POST /api/apply-sessions/{job_id}/skip       {reason, detail}
    GET  /api/apply-sessions/{job_id}/text       the page's visible text
    POST /api/apply-sessions/{job_id}/dialog     {button}: press one button of the dialog over the page
    POST /api/apply-sessions/{job_id}/resume     (you only) back to the front of the queue
    POST /api/apply-sessions/{job_id}/show       bring the paused run's tab to the front of the agent Chrome
    PUT  /api/jobs/{job_id}/priority             {level: low|normal|high|dream}, with Undo
Starting a run needs the job in the apply queue: queueing is what you Confirm (confirm.CONSEQUENTIAL)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from job_dashboard import changes
from job_dashboard.apply import queue as q
from job_dashboard.apply import run_store
from job_dashboard.apply.session_service import ApplySessionError
from job_dashboard.db import init_db


class Answer(BaseModel):
    id: str
    value: Optional[object] = None
    source: str = Field(..., max_length=40)
    citation: Optional[object] = None


class FillBody(BaseModel):
    answers: list[Answer] = Field(default_factory=list, max_length=200)
    accept_suggestions: bool = False


class PauseBody(BaseModel):
    reason: str = Field("needs_answers", max_length=40)
    detail: str = Field("", max_length=2000)
    questions: list[dict] = Field(default_factory=list, max_length=60)


class SkipBody(BaseModel):
    reason: str = Field(..., max_length=40)
    detail: str = Field("", max_length=2000)


class DialogBody(BaseModel):
    button: str = Field(..., min_length=1, max_length=60)


class PriorityBody(BaseModel):
    level: str


def build_apply_session_router(db_path, service) -> APIRouter:
    router = APIRouter()

    def guard(fn, *a, **k):
        try:
            return fn(*a, **k)
        except ApplySessionError as e:
            raise HTTPException(status_code=e.status, detail=e.detail)

    @router.get("/api/apply-sessions/{job_id}")
    def status(job_id: int):
        return service.status(job_id)

    @router.post("/api/apply-sessions/{job_id}")
    def start(job_id: int, request: Request):
        conn = init_db(db_path)
        try:
            row = conn.execute("SELECT state FROM apply_queue WHERE job_id=?", (job_id,)).fetchone()
        finally:
            conn.close()
        if not row or row[0] not in ("queued", "running"):
            raise HTTPException(status_code=409, detail="this job is not in the apply queue: queue it first "
                                "(propose_action POST /api/queue {job_id}) so the user confirms the application")
        return guard(service.start, job_id, request.headers.get("x-agent-session"))

    @router.post("/api/apply-sessions/{job_id}/reach")
    def reach(job_id: int):
        return guard(service.reach, job_id)

    @router.get("/api/apply-sessions/{job_id}/form")
    def form(job_id: int):
        return guard(service.snapshot, job_id)

    @router.post("/api/apply-sessions/{job_id}/fill")
    def fill(job_id: int, body: FillBody):
        return guard(service.fill, job_id, [a.model_dump() for a in body.answers], body.accept_suggestions)

    @router.post("/api/apply-sessions/{job_id}/advance")
    def advance(job_id: int):
        return guard(service.advance, job_id)

    @router.post("/api/apply-sessions/{job_id}/submit")
    def submit(job_id: int):
        return guard(service.submit, job_id)

    @router.post("/api/apply-sessions/{job_id}/pause")
    def pause(job_id: int, body: PauseBody):
        return guard(service.pause, job_id, body.reason, body.detail, body.questions)

    @router.post("/api/apply-sessions/{job_id}/skip")
    def skip(job_id: int, body: SkipBody):
        return guard(service.skip, job_id, body.reason, body.detail)

    @router.post("/api/apply-sessions/{job_id}/dialog")
    def dialog(job_id: int, body: DialogBody):
        return guard(service.dialog, job_id, body.button)

    @router.get("/api/apply-sessions/{job_id}/text")
    def text(job_id: int):
        return guard(service.text, job_id)

    @router.post("/api/apply-sessions/{job_id}/resume")
    def resume(job_id: int):
        conn = init_db(db_path)
        try:
            q.enqueue(conn, job_id, front=True)
        finally:
            conn.close()
        return {"queued": True}

    @router.post("/api/apply-sessions/{job_id}/show")
    def show(job_id: int):
        from job_dashboard import agent_browser
        row = service.status(job_id)
        if not row.get("tab_open") or not row.get("tab_target_id"):
            raise HTTPException(status_code=409, detail="that run's tab is closed; Resume opens it again")
        return {"shown": agent_browser.show_tab(row["tab_target_id"])}

    @router.put("/api/jobs/{job_id}/priority")
    def put_priority(job_id: int, body: PriorityBody):
        if body.level not in run_store.PRIORITIES:
            raise HTTPException(status_code=422, detail=f"level must be one of {', '.join(run_store.PRIORITIES)}")
        conn = init_db(db_path)
        try:
            if conn.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone() is None:
                raise HTTPException(status_code=404, detail="job not found")
            changes.apply(conn, "job", job_id, "priority", body.level)
        finally:
            conn.close()
        return {"job_id": job_id, "priority": body.level}

    return router
