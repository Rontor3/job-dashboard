from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from job_dashboard.api.apply_routes import build_apply_router
from job_dashboard.api.letter_routes import build_letter_router
from job_dashboard.api.refresh_job import RefreshState, default_pipeline_runner
from job_dashboard.api.resume_routes import build_resume_router
from job_dashboard.db import (
    dashboard_stats, distinct_classification_values, init_db, job_detail, query_jobs,
    set_job_status, suspected_duplicates, tracker_jobs,
)

DEFAULT_DB = "data/jobs.db"


class StatusPatch(BaseModel):
    status: Optional[str] = None


def create_app(
    db_path=DEFAULT_DB, pipeline_runner=None, resume_engine=None,
    resume_llm=None, jd_keyword_extractor=None, letter_engine=None,
    screening_engine=None,
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

    ``screening_engine`` overrides the Application Agent's screening-answer
    engine (tests inject a fake with an ``answer(detail, question)``
    surface). The apply routes themselves live in ``api/apply_routes.py``
    (``build_apply_router``), kept out of this module to respect the
    500-line cap; its default engine reuses ``apply.screening.
    draft_screening_answer`` and never 500s.

    The resume routes live in ``api/resume_routes.py`` (``build_resume_
    router``) and the cover-letter/company-resource routes live in
    ``api/letter_routes.py`` (``build_letter_router``), both kept out of
    this module for the same reason.
    """
    app = FastAPI(title="Job Dashboard")
    app.include_router(build_apply_router(db_path, screening_engine))
    app.include_router(
        build_resume_router(db_path, resume_engine, resume_llm, jd_keyword_extractor)
    )
    app.include_router(build_letter_router(db_path, letter_engine))

    @contextmanager
    def db():
        conn = init_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    @app.get("/api/jobs")
    def list_jobs(q: str = None, remote: bool = None, job_type: str = None,
                  source: str = None, industry: str = None, company_type: str = None,
                  status: str = None, min_score: float = None,
                  include_dismissed: bool = False, sort: str = "embed",
                  limit: int = 50, offset: int = 0):
        with db() as conn:
            jobs, total = query_jobs(
                conn, q=q, remote=remote, job_type=job_type, source=source,
                industry=industry, company_type=company_type,
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

    @app.get("/api/tracker")
    def tracker():
        with db() as conn:
            return tracker_jobs(conn)

    @app.get("/api/classifications")
    def classifications():
        with db() as conn:
            return distinct_classification_values(conn)

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

    # Mount frontend static files (SPA with fallback to index.html)
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")

    return app


app = create_app()
