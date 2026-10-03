"""Hiring-digest API: refresh (Selenium search), list, dismiss. Own router to
respect the 500-line cap; ``create_app`` includes it."""
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from job_dashboard.db import (
    init_db, hiring_posts as db_hiring_posts, dismiss_hiring_post, insert_job,
)
from job_dashboard.db_hiring import hiring_post
from job_dashboard.artifacts_store import cover_letters_for_job, save_cover_letter
from job_dashboard.db import job_detail
from job_dashboard.apply import gmail_draft
from job_dashboard.linkedin.contacts import extract_contacts, extract_role, post_to_job, _regex_role, requested_subject
from job_dashboard.linkedin.enrich import research_role, enriched_description
from job_dashboard.linkedin.hiring_digest import KEYWORDS, run_digest
from job_dashboard.linkedin.browser_fetch import LinkedInAuthError
from job_dashboard.match.profile_text import current_resume_text, current_resume_pdf


def build_hiring_router(db_path, hiring_fetcher=None, embed_model=None, role_fn=None) -> APIRouter:
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
            profile_text = current_resume_text()
        except Exception:
            profile_text = ""
        try:
            with db() as conn:
                ranked = run_digest(
                    conn, hiring_fetcher, KEYWORDS, profile_text,
                    embed_model=embed_model,
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    role_fn=role_fn,
                )
        except LinkedInAuthError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:  # browser/driver failure → clear 503, not a 500
            raise HTTPException(status_code=503,
                                detail=f"LinkedIn fetch failed: {e}")
        return {"ranked": len(ranked), "fetched": len(ranked)}

    @router.get("/api/hiring/posts")
    def list_posts(within_hours: int = 168):
        with db() as conn:
            return {"posts": db_hiring_posts(conn, within_hours=within_hours)}

    @router.post("/api/hiring/posts/{post_id}/dismiss")
    def dismiss(post_id: int):
        with db() as conn:
            dismiss_hiring_post(conn, post_id)
        return {"ok": True}

    @router.post("/api/hiring/posts/{post_id}/promote")
    def promote(post_id: int):
        """"Research company": turn a post into a jobs row enriched from the
        company's own pages, and draft the cover letter used as the email body.
        Idempotent."""
        with db() as conn:
            post = hiring_post(conn, post_id)
            if post is None:
                raise HTTPException(status_code=404, detail="post not found")
            row = conn.execute("SELECT id FROM jobs WHERE job_url = ?", (post["url"],)).fetchone()
            if row is None:
                role = extract_role(post)
                job = post_to_job(post, role)
                # Requirements-only posts: read the company's own pages for the
                # rest (role details, about, real apply page).
                info = research_role(post, role, extract_contacts(post["text"], post["url"]))
                job.description = enriched_description(job.description, info)
                if info["apply_url"] and (job.apply_kind == "dm" or any(
                        h in (job.apply_url or "") for h in ("linkedin.com", "licdn.com", "lnkd.in"))):
                    job.apply_url = info["apply_url"]
                    job.apply_kind = "form" if extract_contacts(info["apply_url"])["forms"] else "external"
                insert_job(conn, job)
                row = conn.execute("SELECT id FROM jobs WHERE job_url = ?", (post["url"],)).fetchone()
            job_id = row[0]
            need_letter = not cover_letters_for_job(conn, job_id)
            detail = job_detail(conn, job_id) if need_letter else None
        if need_letter:
            # The research feeds the application email: draft the grounded cover
            # letter now so "Draft email" opens instantly. Never raises.
            from job_dashboard.api.letter_routes import DefaultLetterEngine
            letter = DefaultLetterEngine(db_path).draft(detail)
            with db() as conn:
                save_cover_letter(conn, job_id, None, letter["body"], letter["company_facts_used"])
        return {"job_id": job_id}

    @router.post("/api/hiring/posts/{post_id}/email-draft")
    def email_draft(post_id: int, to: str | None = None):
        """Draft an application email and return a Gmail URL that opens it. With
        the gmail.compose token: a real draft with the user's own résumé PDF
        attached (``current_resume_pdf``; generated CVs are never sent). Without: Gmail's
        compose window prefilled. Never sends."""
        with db() as conn:
            post = hiring_post(conn, post_id)
            if post is None:
                raise HTTPException(status_code=404, detail="post not found")
            emails = extract_contacts(post["text"])["emails"]
            if not emails or (to and to.lower() not in emails):
                raise HTTPException(status_code=422, detail="no such email in this post")
            to = to.lower() if to else emails[0]
            job = conn.execute("SELECT id, title, company FROM jobs WHERE job_url = ?",
                               (post["url"],)).fetchone()
            letters = cover_letters_for_job(conn, job[0]) if job else []
            me = conn.execute("SELECT full_name, phone, linkedin_url, email, notice_period FROM application_profile").fetchone()
        name, phone, linkedin, account, notice = me or ("", "", "", "", "")
        guess = _regex_role(post)
        title = (job[1] if job else "") or post.get("role_title") or guess["title"]
        company = (job[2] if job else "") or post.get("company") or guess["company"]
        role = f"the {title} role" if title else "the opening"
        at = f" at {company}" if company else ""
        # "K, A S Ammna" → "Ammna": first real word (≥2 letters) of the poster's name
        first = next((w for w in re.findall(r"[^\W\d_]+", post["poster_name"] or "") if len(w) > 1), "")
        body = (letters[0]["body"] if letters and letters[0]["body"] else
                f"Hi {first or 'there'},\n\nI came across your post about {role}{at} and would like "
                f"to be considered. I'm a Data Scientist at Tata AIG working on ML fraud-detection "
                f"systems and LLM pipelines; my résumé is attached.\n\n"
                f"Happy to share more or set up a quick call.\n\nBest,\n{name}\n{phone}\n{linkedin}")
        # The subject the post asks for, else a plain description of the opening.
        subject = (requested_subject(post["text"], name, notice)
                   or f"Application for the {title or 'open'} opening{at}")
        # Always the résumé the user supplied — never a generated one.
        pdf = current_resume_pdf()
        # What the recruiter sees — not the internal "current_resume.pdf".
        attach_name = (re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "Resume") + "_Resume.pdf"
        if gmail_draft.authorized() and pdf.exists():
            try:
                d = gmail_draft.create_draft(gmail_draft.compose_message(to, subject, body, pdf, filename=attach_name))
                return {"gmail_url": gmail_draft.draft_url(d["message_id"], account),
                        "attached": attach_name, "to": to}
            except Exception:  # noqa: BLE001 — token revoked etc. → compose URL below
                pass
        return {"gmail_url": gmail_draft.compose_url(to, subject, body, account),
                "attached": None, "to": to}

    return router
