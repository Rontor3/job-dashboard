"""Hiring-digest API: refresh (Selenium search), list, dismiss. Own router to
respect the 500-line cap; ``create_app`` includes it."""
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from job_dashboard.db import (
    init_db, hiring_posts as db_hiring_posts, dismiss_hiring_post,
)
from job_dashboard.linkedin.hiring_digest import KEYWORDS, run_digest
from job_dashboard.linkedin.browser_fetch import LinkedInAuthError
from job_dashboard.match.profile_text import compose_profile_text


def build_hiring_router(db_path, hiring_fetcher=None, embed_model=None) -> APIRouter:
    router = APIRouter()

    @contextmanager
    def db():
        conn = init_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    @router.post("/api/hiring/refresh")
    def refresh():
        if hiring_fetcher is None:
            raise HTTPException(status_code=503,
                                detail="LinkedIn fetcher not configured — set cookies in .env")
        try:
            profile_text = compose_profile_text().text
        except Exception:
            profile_text = ""
        try:
            with db() as conn:
                ranked = run_digest(
                    conn, hiring_fetcher, KEYWORDS, profile_text,
                    embed_model=embed_model,
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                )
        except LinkedInAuthError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:  # browser/driver failure → clear 503, not a 500
            raise HTTPException(status_code=503,
                                detail=f"LinkedIn fetch failed: {e}")
        return {"ranked": len(ranked), "fetched": len(ranked)}

    @router.get("/api/hiring/posts")
    def list_posts(within_hours: int = 24):
        with db() as conn:
            return {"posts": db_hiring_posts(conn, within_hours=within_hours)}

    @router.post("/api/hiring/posts/{post_id}/dismiss")
    def dismiss(post_id: int):
        with db() as conn:
            dismiss_hiring_post(conn, post_id)
        return {"ok": True}

    return router
