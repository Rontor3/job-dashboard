from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from job_dashboard.api.refresh_job import RefreshState, default_pipeline_runner
from job_dashboard.db import (
    dashboard_stats, get_resume, init_db, job_detail, query_jobs,
    resumes_for_job, set_job_status, suspected_duplicates,
)
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


def create_app(
    db_path=DEFAULT_DB, pipeline_runner=None, resume_engine=None,
    resume_llm=None, jd_keyword_extractor=None,
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
    """
    app = FastAPI(title="Job Dashboard")
    default_resume_llm = resume_llm if resume_llm is not None else make_ollama_llm()
    default_jd_keyword_extractor = (
        jd_keyword_extractor if jd_keyword_extractor is not None else extract_jd_keywords
    )

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

    # Mount frontend static files (SPA with fallback to index.html)
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")

    return app


app = create_app()
