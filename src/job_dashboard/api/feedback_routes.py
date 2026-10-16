"""Every click that teaches the Jobs ranking.

POST /api/jobs/{id}/feedback       Skip (with reasons) / More-like-this — re-ranks the Jobs tab
GET  /api/preferences              what the clicks taught (likes, dislikes, blocked companies) + skip reasons
DELETE /api/preferences/{feature}  forget one learned preference
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from job_dashboard.db import init_db, set_job_status
from job_dashboard.match import preferences


class FeedbackBody(BaseModel):
    verdict: str
    reasons: list[str] = []


def build_feedback_router(db_path) -> APIRouter:
    router = APIRouter()

    def db():
        conn = init_db(db_path)
        preferences.ensure(conn)
        return conn

    @router.post("/api/jobs/{job_id}/feedback")
    def feedback(job_id: int, body: FeedbackBody):
        conn = db()
        try:
            if conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone() is None:
                raise HTTPException(status_code=404, detail="job not found")
            try:
                preferences.record(conn, job_id, body.verdict, body.reasons)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))
            if body.verdict == "skip":
                set_job_status(conn, job_id, "dismissed")
            return preferences.summary(preferences.learn(conn))
        finally:
            conn.close()

    @router.get("/api/preferences")
    def get_preferences():
        conn = db()
        try:
            return {**preferences.summary(preferences.learn(conn)),
                    "skip_reasons": [{"key": k, "label": v} for k, v in preferences.SKIP_REASONS.items()]}
        finally:
            conn.close()

    @router.delete("/api/preferences/{feature:path}")
    def forget(feature: str):
        conn = db()
        try:
            preferences.mute(conn, feature)
            return preferences.summary(preferences.learn(conn))
        finally:
            conn.close()

    return router
