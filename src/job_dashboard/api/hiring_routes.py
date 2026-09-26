"""Hiring-digest API: refresh (Selenium search), list, dismiss. Own router to
respect the 500-line cap; ``create_app`` includes it."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from job_dashboard.db import (
    init_db, hiring_posts as db_hiring_posts, dismiss_hiring_post, insert_job,
)
from job_dashboard.db_hiring import hiring_post
from job_dashboard.artifacts_store import resumes_for_job, cover_letters_for_job
from job_dashboard.apply import gmail_draft
from job_dashboard.linkedin.contacts import extract_contacts, extract_role, post_to_job
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

    @router.post("/api/hiring/posts/{post_id}/promote")
    def promote(post_id: int):
        """Turn a post into a jobs row so the per-job tailoring (résumé, company
        research, cover letter, career_agent) runs on it. Idempotent."""
        with db() as conn:
            post = hiring_post(conn, post_id)
            if post is None:
                raise HTTPException(status_code=404, detail="post not found")
            row = conn.execute("SELECT id FROM jobs WHERE job_url = ?", (post["url"],)).fetchone()
            if row is None:
                insert_job(conn, post_to_job(post, extract_role(post)))
                row = conn.execute("SELECT id FROM jobs WHERE job_url = ?", (post["url"],)).fetchone()
        return {"job_id": row[0]}

    @router.post("/api/hiring/posts/{post_id}/email-draft")
    def email_draft(post_id: int):
        """Gmail DRAFT to the post's email with the newest tailored résumé for the
        promoted job attached. Never sends."""
        with db() as conn:
            post = hiring_post(conn, post_id)
            if post is None:
                raise HTTPException(status_code=404, detail="post not found")
            emails = extract_contacts(post["text"])["emails"]
            if not emails:
                raise HTTPException(status_code=422, detail="no email in this post")
            job = conn.execute("SELECT id, title, company FROM jobs WHERE job_url = ?",
                               (post["url"],)).fetchone()
            resumes = resumes_for_job(conn, job[0]) if job else []
            if not resumes or not Path(resumes[0]["pdf_path"] or "").exists():
                raise HTTPException(status_code=409,
                                    detail="generate a tailored résumé for this post first")
            letters = cover_letters_for_job(conn, job[0])
            me = conn.execute("SELECT full_name, phone, linkedin_url FROM application_profile").fetchone()
        name, phone, linkedin = me or ("", "", "")
        first = (post["poster_name"] or "").split(" ")[0]
        body = (letters[0]["body"] if letters and letters[0]["body"] else
                f"Hi {first},\n\nI came across your post about the {job[1]} role at {job[2]} "
                f"and would like to be considered. My résumé, tailored to the role, is attached.\n\n"
                f"Happy to share more or set up a quick call.\n\nBest,\n{name}\n{phone}\n{linkedin}")
        msg = gmail_draft.compose_message(emails[0], f"Application: {job[1]} — {name}",
                                          body, Path(resumes[0]["pdf_path"]))
        try:
            draft_id = gmail_draft.create_draft(msg)
        except gmail_draft.DraftAuthError as e:
            raise HTTPException(status_code=503, detail=str(e))
        return {"draft_id": draft_id, "to": emails[0]}

    return router
