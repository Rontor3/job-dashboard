"""Cover-letter and company-resource API endpoints: research/draft/generate,
company-research/company-resources/select, per-job cover-letter list, and
PDF serving. Kept as its own ``APIRouter`` (not inline in ``app.py``) to
respect the 500-line cap; ``create_app`` includes this router.
"""
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from job_dashboard.db import (
    company_key, company_resources_for, cover_letters_for_job, get_cover_letter,
    init_db, job_detail, save_cover_letter, selected_resources_for,
    set_selected_resources, upsert_company_resources,
)
from job_dashboard.letter.company_research import Fact, ResearchBundle, company_research
from job_dashboard.letter.draft import draft_cover_letter
from job_dashboard.letter.grounding import check_grounding
from job_dashboard.letter.render_letter import render_letter_pdf
from job_dashboard.letter.research_store import resources_from_bundle
from job_dashboard.match.profile_text import compose_profile_text


class CoverLetterGenerateRequest(BaseModel):
    body: str


class ResourceSelectRequest(BaseModel):
    source_urls: list[str] = []


def _public_resources(rows):
    return [{"source_url": r["source_url"], "title": r["title"],
             "summary": r["summary"], "selected": r["selected"]} for r in rows]


class DefaultLetterEngine:
    """Real wiring for cover-letter research/draft/generate, mirroring how
    ``resume_engine`` defaults to real modules. Unlike ``resume_engine``
    (which stays ``None`` and is branched around per-route), this default is
    always a concrete object — every route just calls its methods — so a
    test's fake ``letter_engine`` is a drop-in replacement with the exact
    same three-method surface (``research``/``draft``/``generate``).

    Each method takes the full job ``detail`` dict (company/title/
    description/strengths) rather than loose args, since drafting needs all
    of them. Every method is graceful: TinyFish/Ollama failures degrade to
    an empty bundle / general-template body (see ``company_research`` and
    ``draft_cover_letter``'s own never-raise contracts) rather than raising,
    so these routes never 500 on a down dependency.
    """

    def __init__(self, db_path):
        self.db_path = db_path

    def _research_bundle(self, detail):
        return company_research(
            detail.get("company") or "",
            detail.get("title") or "",
            detail.get("description") or "",
        )

    def _company_key(self, detail):
        return company_key(detail.get("company") or "")

    def research(self, detail):
        bundle = self._research_bundle(detail)
        return {
            "facts": [{"text": f.text, "source_url": f.source_url} for f in bundle.facts],
            "queries_used": bundle.queries_used,
            "empty": bundle.empty,
        }

    def gather_resources(self, detail):
        """Fresh TinyFish research, grouped into per-source resources and
        persisted (upserted) for this company, then returned in full."""
        bundle = self._research_bundle(detail)
        ck = self._company_key(detail)
        conn = init_db(self.db_path)
        try:
            upsert_company_resources(conn, ck, [
                {"source_url": r.source_url, "title": r.title, "summary": r.summary}
                for r in resources_from_bundle(bundle)
            ])
            rows = company_resources_for(conn, ck)
        finally:
            conn.close()
        return {"company": detail.get("company"), "resources": _public_resources(rows)}

    def list_resources(self, detail):
        """Previously-gathered resources for this company (no network call)."""
        conn = init_db(self.db_path)
        try:
            rows = company_resources_for(conn, self._company_key(detail))
        finally:
            conn.close()
        return {"company": detail.get("company"), "resources": _public_resources(rows)}

    def select_resources(self, detail, source_urls):
        """Persist the user's curated pick (capped at 2 by ``set_selected_resources``)."""
        ck = self._company_key(detail)
        conn = init_db(self.db_path)
        try:
            set_selected_resources(conn, ck, source_urls or [])
            rows = company_resources_for(conn, ck)
        finally:
            conn.close()
        return {"company": detail.get("company"), "resources": _public_resources(rows)}

    def draft(self, detail):
        """Ground the draft in the user's selected resources when present;
        else fall back to the top-2 gathered-but-unselected resources; else
        fall back to a fresh research call (today's behavior when nothing
        has been gathered yet)."""
        ck = self._company_key(detail)
        conn = init_db(self.db_path)
        try:
            chosen = selected_resources_for(conn, ck) or company_resources_for(conn, ck)[:2]
        finally:
            conn.close()
        if chosen:
            bundle = ResearchBundle(
                facts=[Fact(text=r["summary"], source_url=r["source_url"]) for r in chosen],
                queries_used=[], empty=False,
            )
        else:
            bundle = self._research_bundle(detail)
        try:
            profile_text = compose_profile_text().text
        except Exception:
            # Missing/empty candidate profile file -> draft with no profile
            # context rather than 500ing; draft_cover_letter tolerates "".
            profile_text = ""
        result = draft_cover_letter(detail, profile_text, bundle)
        job_text = " ".join(
            str(detail.get(k) or "") for k in ("title", "company", "description")
        )
        grounding = check_grounding(result["body"], bundle, profile_text, job_text)
        return {
            "body": result["body"],
            "company_facts_used": result["company_facts_used"],
            "flags": result["flags"],
            "grounding": {"unsupported_company_claims": grounding.unsupported_company_claims},
        }

    def generate(self, job_id, body):
        out_dir = Path(self.db_path).parent / "cover_letters"
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = render_letter_pdf(body, out_dir)  # may raise RuntimeError (no lualatex)

        conn = init_db(self.db_path)
        try:
            cover_letter_id = save_cover_letter(conn, job_id, str(pdf_path), body, [])
        finally:
            conn.close()

        return {
            "cover_letter_id": cover_letter_id,
            "pdf_url": f"/api/cover-letters/{cover_letter_id}/pdf",
        }


def build_letter_router(db_path, letter_engine=None) -> APIRouter:
    router = APIRouter()
    engine = letter_engine if letter_engine is not None else DefaultLetterEngine(db_path)

    @contextmanager
    def db():
        conn = init_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    @router.post("/api/jobs/{job_id}/cover-letter/research")
    def research_cover_letter(job_id: int):
        """Research company facts for a job (TinyFish). Never 500s — a down
        TinyFish degrades to an empty bundle (see ``DefaultLetterEngine``)."""
        with db() as conn:
            detail = job_detail(conn, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")
        return engine.research(detail)

    @router.post("/api/jobs/{job_id}/cover-letter/draft")
    def draft_job_cover_letter(job_id: int):
        """Draft a grounded cover letter (research + draft + grounding
        guard). Never 500s — a down TinyFish/Ollama degrades to a general
        template body (see ``DefaultLetterEngine``)."""
        with db() as conn:
            detail = job_detail(conn, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")
        return engine.draft(detail)

    @router.post("/api/jobs/{job_id}/cover-letter/generate")
    def generate_job_cover_letter(job_id: int, body: CoverLetterGenerateRequest):
        """Render the (human-reviewed) letter body to PDF and persist it."""
        with db() as conn:
            detail = job_detail(conn, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")

        try:
            result = engine.generate(job_id, body.body)
        except RuntimeError as e:
            if "lualatex not found" in str(e):
                raise HTTPException(
                    status_code=503,
                    detail="install MacTeX — lualatex not found",
                )
            raise
        return result

    @router.post("/api/jobs/{job_id}/company-research")
    def gather_company_research(job_id: int):
        """Gather fresh TinyFish research grouped into curatable resources
        and persist them for this company. Never 500s — a down TinyFish
        degrades to an empty resource list (see ``DefaultLetterEngine``)."""
        with db() as conn:
            detail = job_detail(conn, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")
        return engine.gather_resources(detail)

    @router.get("/api/jobs/{job_id}/company-resources")
    def get_company_resources(job_id: int):
        """Previously-gathered resources for this job's company."""
        with db() as conn:
            detail = job_detail(conn, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")
        return engine.list_resources(detail)

    @router.post("/api/jobs/{job_id}/company-resources/select")
    def select_company_resources(job_id: int, body: ResourceSelectRequest):
        """Persist the user's curated pick (capped at 2) for grounding."""
        with db() as conn:
            detail = job_detail(conn, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")
        return engine.select_resources(detail, body.source_urls)

    @router.get("/api/jobs/{job_id}/cover-letters")
    def list_job_cover_letters(job_id: int):
        """Get all cover letters for a job."""
        with db() as conn:
            detail = job_detail(conn, job_id)
            if detail is None:
                raise HTTPException(status_code=404, detail="job not found")
            letters = cover_letters_for_job(conn, job_id)
        return {"cover_letters": letters}

    @router.get("/api/cover-letters/{cover_letter_id}/pdf")
    def get_cover_letter_pdf(cover_letter_id: int):
        """Serve a cover letter PDF."""
        with db() as conn:
            letter = get_cover_letter(conn, cover_letter_id)
        if letter is None or not letter.get("pdf_path"):
            raise HTTPException(status_code=404, detail="cover letter not found")

        pdf_path = Path(letter["pdf_path"])
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail="PDF file not found")

        return FileResponse(pdf_path, media_type="application/pdf")

    return router
