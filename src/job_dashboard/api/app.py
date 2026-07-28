from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from job_dashboard.api.refresh_job import RefreshState, default_pipeline_runner
from job_dashboard.db import (
    cover_letters_for_job, dashboard_stats, get_cover_letter, get_resume,
    init_db, job_detail, query_jobs, resumes_for_job, save_cover_letter,
    set_job_status, suspected_duplicates,
)
from job_dashboard.letter.company_research import company_research
from job_dashboard.letter.draft import draft_cover_letter
from job_dashboard.letter.grounding import check_grounding
from job_dashboard.letter.render_letter import render_letter_pdf
from job_dashboard.match.profile_text import compose_profile_text
from job_dashboard.resume.engine import generate_resume, suggest_blocks
from job_dashboard.resume.segments import load_segments
from job_dashboard.resume.render import render_pdf
from job_dashboard.resume.ats import ats_check
from job_dashboard.resume.fit import fit_to_page
from job_dashboard.resume.keyword_map import (
    GapKeyword, Rephrasing, extract_keywords, simple_deep_rank,
)
from job_dashboard.resume.resume_llm import extract_jd_keywords, make_ollama_llm

DEFAULT_DB = "data/jobs.db"


class StatusPatch(BaseModel):
    status: Optional[str] = None


class ResumeGenerateRequest(BaseModel):
    block_ids: list[str]
    accepted_rephrasings: list[dict] = []


class CoverLetterGenerateRequest(BaseModel):
    body: str


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

    def research(self, detail):
        bundle = self._research_bundle(detail)
        return {
            "facts": [{"text": f.text, "source_url": f.source_url} for f in bundle.facts],
            "queries_used": bundle.queries_used,
            "empty": bundle.empty,
        }

    def draft(self, detail):
        bundle = self._research_bundle(detail)
        try:
            profile_text = compose_profile_text().text
        except Exception:
            # Missing/empty candidate profile file -> draft with no profile
            # context rather than 500ing; draft_cover_letter tolerates "".
            profile_text = ""
        result = draft_cover_letter(detail, profile_text, bundle)
        grounding = check_grounding(result["body"], bundle, profile_text)
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


def create_app(
    db_path=DEFAULT_DB, pipeline_runner=None, resume_engine=None,
    resume_llm=None, jd_keyword_extractor=None, letter_engine=None,
):
    """``resume_llm`` overrides the default engine's ``LlmFn`` (tests inject
    a fake here to exercise the default ``resume_engine=None`` wiring
    without touching real Ollama). Defaults to ``make_ollama_llm()``, a
    local Ollama call — building that closure does NOT touch the network
    (``make_ollama_llm`` never makes an HTTP call itself); it's only
    invoked, per-keyword, from inside ``suggest_resume`` below, where every
    failure is already caught (see ``resume_llm.make_ollama_llm`` and
    ``keyword_map.propose_rephrasings``) so an unreachable Ollama can never
    turn into a 500.

    ``jd_keyword_extractor`` overrides the clean-JD-tech-keyword source
    (tests inject a fake here too). Defaults to ``resume_llm.
    extract_jd_keywords`` — a single Ollama call per suggest request; same
    never-raises contract as above, so an unreachable Ollama degrades to
    the crude JD-tokenization fallback in ``suggest_resume``, never a 500.

    ``letter_engine`` overrides the cover-letter engine (tests inject a fake
    with a ``research``/``draft``/``generate`` surface here, so no real
    TinyFish/Ollama/LaTeX call is ever made in the suite). Defaults to
    ``DefaultLetterEngine(db_path)``, which wires the real
    ``letter.company_research``/``letter.draft``/``letter.grounding``/
    ``letter.render_letter`` modules — each of those already never raises on
    a down TinyFish/Ollama (see their own docstrings), so the cover-letter
    routes below degrade gracefully (empty research / general-template
    draft) rather than 500ing.
    """
    app = FastAPI(title="Job Dashboard")
    default_resume_llm = resume_llm if resume_llm is not None else make_ollama_llm()
    default_jd_keyword_extractor = (
        jd_keyword_extractor if jd_keyword_extractor is not None else extract_jd_keywords
    )
    engine = letter_engine if letter_engine is not None else DefaultLetterEngine(db_path)

    @contextmanager
    def db():
        conn = init_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    @app.get("/api/jobs")
    def list_jobs(q: str = None, remote: bool = None, job_type: str = None,
                  source: str = None, status: str = None, min_score: float = None,
                  include_dismissed: bool = False, sort: str = "embed",
                  limit: int = 50, offset: int = 0):
        with db() as conn:
            jobs, total = query_jobs(
                conn, q=q, remote=remote, job_type=job_type, source=source,
                status=status, min_score=min_score,
                include_dismissed=include_dismissed, sort=sort,
                limit=limit, offset=offset,
            )
        return {"jobs": jobs, "total": total}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: int):
        with db() as conn:
            detail = job_detail(conn, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")
        return detail

    @app.patch("/api/jobs/{job_id}/status")
    def patch_status(job_id: int, body: StatusPatch):
        with db() as conn:
            try:
                set_job_status(conn, job_id, body.status)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            except KeyError:
                raise HTTPException(status_code=404, detail="job not found")
        return {"ok": True, "status": body.status}

    @app.get("/api/duplicates")
    def list_duplicates():
        with db() as conn:
            return {"duplicates": suspected_duplicates(conn)}

    @app.get("/api/stats")
    def stats():
        with db() as conn:
            return dashboard_stats(conn)

    state = RefreshState()
    runner = pipeline_runner or default_pipeline_runner

    @app.post("/api/refresh")
    def start_refresh():
        started = state.start(lambda on_stage: runner(db_path, on_stage))
        if not started:
            raise HTTPException(status_code=409, detail="refresh already running")
        return {"started": True}

    @app.get("/api/refresh/status")
    def refresh_status():
        return state.snapshot()

    # Resume API endpoints
    @app.get("/api/resume/segments")
    def list_segments():
        """Return block manifest (id, kind, title, tags, exclusive_group)."""
        segments = load_segments()
        return {
            "segments": [
                {
                    "id": s.id,
                    "kind": s.kind,
                    "title": s.title,
                    "tags": s.tags,
                    "exclusive_group": s.exclusive_group,
                }
                for s in segments
            ]
        }

    @app.post("/api/jobs/{job_id}/resume/suggest")
    def suggest_resume(job_id: int):
        """Suggest resume blocks for a job."""
        with db() as conn:
            detail = job_detail(conn, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")

        if resume_engine is None:
            segments = load_segments()
            jd_text = detail["description"]

            # Rephrasing keyword source: clean JD tech keywords from a
            # single LLM extraction call (e.g. "kubernetes", "pytorch"),
            # cross-referenced against the resume's own text so the LLM
            # isn't asked to reword blocks that already truthfully cover a
            # term. Deliberately NOT the stored deep-rank gaps below —
            # those are narrative fit-gap text ("5+ years required...")
            # meant for human display, not clean single-term keywords a
            # rephrasing prompt can act on.
            try:
                extracted_keywords = default_jd_keyword_extractor(jd_text) or []
            except Exception:
                # Defensive: extract_jd_keywords itself never raises, but an
                # injected/alternate extractor might (e.g. simulating
                # Ollama down) — treat that the same as "extraction
                # unavailable" rather than letting it 500 the endpoint.
                extracted_keywords = []
            if extracted_keywords:
                covered = set()
                for seg in segments:
                    covered |= set(extract_keywords(seg.text))
                rephrasing_keywords = [
                    kw for kw in extracted_keywords if kw.lower() not in covered
                ]
            else:
                # Extraction unavailable (e.g. Ollama down) -> fall back to
                # crude JD tokenization, same as before this fix.
                rephrasing_keywords = None

            result = suggest_blocks(
                segments, jd_text, simple_deep_rank,
                llm=default_resume_llm,
                keywords=rephrasing_keywords or None,
            )

            # Displayed gap chips are the stored deep-rank narrative gaps
            # (from /rank's record_llm_evaluation) when present — real
            # fit-gap feedback for a human, kept separate from the
            # extracted keywords driving rephrasing above. Falls back to
            # the engine's own JD-tokenization-based gap computation when
            # nothing is stored (unchanged prior behavior).
            stored_gaps = detail.get("gaps") or []
            if stored_gaps:
                result["gaps"] = [GapKeyword(jd_keyword=g) for g in stored_gaps]
        else:
            result = resume_engine.suggest_blocks(
                detail["description"], job_id
            )

        return result

    @app.post("/api/jobs/{job_id}/resume/generate")
    def generate_job_resume(job_id: int, body: ResumeGenerateRequest):
        """Generate a tailored resume PDF."""
        with db() as conn:
            detail = job_detail(conn, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")

        if resume_engine is None:
            segments = load_segments()
            # Parse accepted rephrasings from request
            accepted_rephrasings = []
            for r in body.accepted_rephrasings:
                accepted_rephrasings.append(
                    Rephrasing(
                        block_id=r.get("block_id"),
                        original_text=r.get("original_text", ""),
                        proposed_text=r.get("proposed_text", ""),
                        jd_keyword=r.get("jd_keyword", ""),
                        confidence=r.get("confidence", "equivalent"),
                        needs_interview_prep=r.get("needs_interview_prep", False),
                    )
                )

            out_dir = Path(db_path).parent / "resumes"
            out_dir.mkdir(parents=True, exist_ok=True)

            try:
                with db() as conn:
                    result = generate_resume(
                        conn,
                        job_id,
                        body.block_ids,
                        accepted_rephrasings,
                        segments=segments,
                        jd_text=detail["description"],
                        render_pdf=render_pdf,
                        ats_check=ats_check,
                        fit_to_page=fit_to_page,
                        out_dir=out_dir,
                    )
            except RuntimeError as e:
                if "lualatex not found" in str(e):
                    raise HTTPException(
                        status_code=503,
                        detail="install MacTeX — lualatex not found",
                    )
                raise

            # Convert ats_report to dict if it's a dataclass
            ats_report_dict = result["ats_report"]
            if hasattr(result["ats_report"], "__dataclass_fields__"):
                ats_report_dict = asdict(result["ats_report"])

            return {
                "resume_id": result["resume_id"],
                "pdf_url": f"/api/resumes/{result['resume_id']}/pdf",
                "ats_report": ats_report_dict,
                "blocks_used": result["blocks_used"],
                "cut_lines": result["cut_lines"],
                "interview_prep": result["interview_prep"],
            }
        else:
            try:
                result = resume_engine.generate_resume(
                    job_id, body.block_ids, body.accepted_rephrasings
                )
            except RuntimeError as e:
                if "lualatex not found" in str(e):
                    raise HTTPException(
                        status_code=503,
                        detail="install MacTeX — lualatex not found",
                    )
                raise
            return result

    @app.get("/api/jobs/{job_id}/resumes")
    def list_job_resumes(job_id: int):
        """Get all resumes for a job."""
        with db() as conn:
            detail = job_detail(conn, job_id)
            if detail is None:
                raise HTTPException(status_code=404, detail="job not found")
            resumes = resumes_for_job(conn, job_id)
        return {"resumes": resumes}

    @app.get("/api/resumes/{resume_id}/pdf")
    def get_resume_pdf(resume_id: int):
        """Serve a resume PDF."""
        with db() as conn:
            resume = get_resume(conn, resume_id)
        if resume is None or not resume.get("pdf_path"):
            raise HTTPException(status_code=404, detail="resume not found")

        pdf_path = Path(resume["pdf_path"])
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail="PDF file not found")

        return FileResponse(pdf_path, media_type="application/pdf")

    # Cover-letter API endpoints
    @app.post("/api/jobs/{job_id}/cover-letter/research")
    def research_cover_letter(job_id: int):
        """Research company facts for a job (TinyFish). Never 500s — a down
        TinyFish degrades to an empty bundle (see ``DefaultLetterEngine``)."""
        with db() as conn:
            detail = job_detail(conn, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")
        return engine.research(detail)

    @app.post("/api/jobs/{job_id}/cover-letter/draft")
    def draft_job_cover_letter(job_id: int):
        """Draft a grounded cover letter (research + draft + grounding
        guard). Never 500s — a down TinyFish/Ollama degrades to a general
        template body (see ``DefaultLetterEngine``)."""
        with db() as conn:
            detail = job_detail(conn, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")
        return engine.draft(detail)

    @app.post("/api/jobs/{job_id}/cover-letter/generate")
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

    @app.get("/api/jobs/{job_id}/cover-letters")
    def list_job_cover_letters(job_id: int):
        """Get all cover letters for a job."""
        with db() as conn:
            detail = job_detail(conn, job_id)
            if detail is None:
                raise HTTPException(status_code=404, detail="job not found")
            letters = cover_letters_for_job(conn, job_id)
        return {"cover_letters": letters}

    @app.get("/api/cover-letters/{cover_letter_id}/pdf")
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

    # Mount frontend static files (SPA with fallback to index.html)
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")

    return app


app = create_app()
