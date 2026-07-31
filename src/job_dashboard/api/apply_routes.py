"""Application Agent API: profile, per-job package, screening answers,
ATS field-maps, and application records. Kept as its own ``APIRouter`` (not
inline in ``app.py``) to respect the 500-line cap; ``create_app`` includes
this router.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from job_dashboard.apply.ats_maps import detect_ats, load_ats_map
from job_dashboard.apply.package import assemble_application_package
from job_dashboard.apply.screening import draft_screening_answer
from job_dashboard.apply.store import (
    get_application, get_application_profile, save_application,
    save_application_profile,
)
from job_dashboard.db import company_key, init_db, job_detail, selected_resources_for
from job_dashboard.letter.company_research import Fact, ResearchBundle, company_research
from job_dashboard.match.profile_text import compose_profile_text


class ApplicationProfileRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    work_authorization: Optional[str] = None
    years_experience: Optional[str] = None
    willing_to_relocate: Optional[bool] = None
    notice_period: Optional[str] = None
    salary_expectation: Optional[str] = None


class ScreeningAnswerRequest(BaseModel):
    question: str


class ApplicationRequest(BaseModel):
    resume_id: Optional[int] = None
    cover_letter_id: Optional[int] = None
    screening: Optional[list] = None
    ats: Optional[str] = None
    status: str = "prepared"


class DefaultScreeningEngine:
    """Real wiring for screening answers, mirroring ``DefaultLetterEngine``'s
    graceful-degradation contract: builds a grounded prompt from the saved
    candidate profile, the company's selected research resources (falling
    back to a fresh ``company_research`` call when nothing is selected/
    gathered yet), and the most recent resume's text (best-effort, from the
    resume-segment library) — then delegates to
    ``draft_screening_answer``, which itself never raises. Any failure
    while assembling that context also degrades to an empty bundle rather
    than a 500.
    """

    def __init__(self, db_path):
        self.db_path = db_path

    def _profile_text(self):
        try:
            return compose_profile_text().text
        except Exception:
            return ""

    def _research_bundle(self, detail):
        conn = init_db(self.db_path)
        try:
            ck = company_key(detail.get("company") or "")
            chosen = selected_resources_for(conn, ck)
        finally:
            conn.close()
        if chosen:
            return ResearchBundle(
                facts=[Fact(text=r["summary"], source_url=r["source_url"]) for r in chosen],
                queries_used=[], empty=False,
            )
        return company_research(
            detail.get("company") or "", detail.get("title") or "",
            detail.get("description") or "",
        )

    def _resume_text(self, job_id):
        try:
            from job_dashboard.db import resumes_for_job
            from job_dashboard.resume.segments import load_segments

            conn = init_db(self.db_path)
            try:
                resumes = resumes_for_job(conn, job_id)
            finally:
                conn.close()
            if not resumes:
                return ""
            block_ids = set(resumes[0].get("blocks_used") or [])
            segments = load_segments()
            return "\n".join(s.text for s in segments if s.id in block_ids)
        except Exception:
            return ""

    def answer(self, detail, question):
        try:
            profile_text = self._profile_text()
            bundle = self._research_bundle(detail)
            resume_text = self._resume_text(detail.get("id"))
        except Exception:
            profile_text, resume_text = "", ""
            bundle = ResearchBundle(facts=[], queries_used=[], empty=True)
        return draft_screening_answer(
            detail, question, profile_text, bundle, resume_text=resume_text,
        )


def build_apply_router(db_path, screening_engine=None) -> APIRouter:
    router = APIRouter()
    engine = screening_engine if screening_engine is not None else DefaultScreeningEngine(db_path)

    def db():
        return init_db(db_path)

    @router.get("/api/application-profile")
    def get_profile():
        conn = db()
        try:
            profile = get_application_profile(conn)
        finally:
            conn.close()
        return profile or {}

    @router.put("/api/application-profile")
    def put_profile(body: ApplicationProfileRequest):
        conn = db()
        try:
            saved = save_application_profile(conn, body.model_dump())
        finally:
            conn.close()
        return saved

    @router.get("/api/jobs/{job_id}/application-package")
    def get_package(job_id: int):
        conn = db()
        try:
            detail = job_detail(conn, job_id)
            if detail is None:
                raise HTTPException(status_code=404, detail="job not found")
            pkg = assemble_application_package(conn, job_id)
        finally:
            conn.close()
        pkg["ats_hint"] = detect_ats(detail.get("job_url"))
        return pkg

    @router.post("/api/jobs/{job_id}/screening-answer")
    def post_screening_answer(job_id: int, body: ScreeningAnswerRequest):
        conn = db()
        try:
            detail = job_detail(conn, job_id)
        finally:
            conn.close()
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")
        try:
            return engine.answer(detail, body.question)
        except Exception:
            # engine.answer should already be graceful, but this route must
            # never 500 regardless of how a caller-supplied engine behaves.
            return {"answer": "", "flags": ["general_fallback"]}

    @router.get("/api/ats-map/{name}")
    def get_ats_map(name: str):
        try:
            return load_ats_map(name)
        except (FileNotFoundError, KeyError):
            raise HTTPException(status_code=404, detail="unknown ats")

    @router.post("/api/jobs/{job_id}/application")
    def post_application(job_id: int, body: ApplicationRequest):
        conn = db()
        try:
            detail = job_detail(conn, job_id)
            if detail is None:
                raise HTTPException(status_code=404, detail="job not found")
            application_id = save_application(
                conn, job_id, resume_id=body.resume_id,
                cover_letter_id=body.cover_letter_id, screening=body.screening,
                ats=body.ats, status=body.status,
            )
        finally:
            conn.close()
        return {"application_id": application_id, "status": body.status}

    @router.get("/api/jobs/{job_id}/application")
    def get_application_route(job_id: int):
        conn = db()
        try:
            application = get_application(conn, job_id)
        finally:
            conn.close()
        return application or {}

    return router
