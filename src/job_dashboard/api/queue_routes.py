"""The apply queue API: add / reorder / remove jobs, start and pause the runner,
and the per-board standing authorization to auto-submit.

The runner launches career_agent through the same AgentRunState the
single-job /apply-agent route uses, so the two never drive Chrome at once.
"""
from __future__ import annotations

import os
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from job_dashboard import qa_store
from job_dashboard.apply import queue as q
from job_dashboard.apply.queue_runner import QueueRunner
from job_dashboard.db import init_db, set_job_status

AUTOSUBMIT_PREFIX = "autosubmit_"


class QueueAdd(BaseModel):
    job_id: int
    front: bool = False
    start: bool = False


class QueueMove(BaseModel):
    before: Optional[int] = None


class AutosubmitSet(BaseModel):
    board: str
    on: bool


def make_agent_launch(state, poll_s: float = 2.0):
    """launch(job_id, argv, result_path) -> exit code, via the shared AgentRunState.
    Waits for a busy agent (e.g. a manual /apply-agent run) instead of failing."""
    from job_dashboard.api.agent_routes import REPO_ROOT, _ensure_cdp_chrome, _log_path

    def launch(job_id, argv, result_path):
        from career_agent.config.settings import load_settings
        cdp_url = load_settings().cdp_url
        if cdp_url:
            problem = _ensure_cdp_chrome(cdp_url)
            if problem:
                raise RuntimeError(problem)
        env = {**os.environ, "PYTHONPATH": "src", "PYTHONUNBUFFERED": "1"}
        while not state.start(job_id, argv, str(REPO_ROOT), env, _log_path(job_id)):
            time.sleep(poll_s)
        return state.wait()

    return launch


def _boards() -> list[str]:
    return sorted(k[len(AUTOSUBMIT_PREFIX):] for k in qa_store.DEFAULT_SETTINGS if k.startswith(AUTOSUBMIT_PREFIX))


def build_queue_router(db_path, runner: QueueRunner) -> APIRouter:
    router = APIRouter()

    def db():
        return init_db(db_path)

    def snapshot(conn) -> dict:
        return {"items": q.list_queue(conn), **runner.status()}

    @router.get("/api/queue")
    def get_queue():
        conn = db()
        try:
            return snapshot(conn)
        finally:
            conn.close()

    @router.post("/api/queue")
    def add(body: QueueAdd):
        conn = db()
        try:
            row = conn.execute("SELECT status FROM jobs WHERE id = ?", (body.job_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="job not found")
            q.enqueue(conn, body.job_id, front=body.front)
            if row[0] is None:
                set_job_status(conn, body.job_id, "saved")        # queued jobs show on the tracker
            if body.start:
                runner.start()
            return snapshot(conn)
        finally:
            conn.close()

    @router.delete("/api/queue/{job_id}")
    def remove(job_id: int):
        if runner.status()["job_id"] == job_id:
            raise HTTPException(status_code=409, detail="that job is being filled right now")
        conn = db()
        try:
            q.remove(conn, job_id)
            return snapshot(conn)
        finally:
            conn.close()

    @router.post("/api/queue/{job_id}/move")
    def move(job_id: int, body: QueueMove):
        conn = db()
        try:
            try:
                q.move(conn, job_id, body.before)
            except KeyError:
                raise HTTPException(status_code=404, detail="job not in queue")
            return snapshot(conn)
        finally:
            conn.close()

    @router.post("/api/queue/start")
    def start():
        runner.start()
        return runner.status()

    @router.post("/api/queue/pause")
    def pause():
        runner.pause()
        return runner.status()

    def toggles(conn) -> dict:
        return {b: qa_store.get_setting(conn, AUTOSUBMIT_PREFIX + b) == "1" for b in _boards()}

    @router.get("/api/queue/autosubmit")
    def get_autosubmit():
        conn = db()
        try:
            return toggles(conn)
        finally:
            conn.close()

    @router.put("/api/queue/autosubmit")
    def set_autosubmit(body: AutosubmitSet):
        if body.board not in _boards():
            raise HTTPException(status_code=422, detail=f"unknown board {body.board!r}")
        conn = db()
        try:
            qa_store.set_setting(conn, AUTOSUBMIT_PREFIX + body.board, "1" if body.on else "0")
            return toggles(conn)
        finally:
            conn.close()

    return router
