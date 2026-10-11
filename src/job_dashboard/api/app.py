from job_dashboard import paths
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from job_dashboard import change_entities  # noqa: F401 — registers what Undo can write back
from job_dashboard import changes
from job_dashboard import config as settings
from job_dashboard.match import preferences
from job_dashboard.tracker import set_status
from job_dashboard.api.agent_routes import AgentRunState, build_agent_router
from job_dashboard.api.mail_routes import MailScanner, build_mail_router
from job_dashboard.api.queue_routes import build_queue_router
from job_dashboard.apply.queue_control import QueueControl
from job_dashboard.apply.queue_runner import QueueRunner
from job_dashboard.api.apply_routes import build_apply_router
from job_dashboard.api.change_routes import ChangeMiddleware, build_change_router
from job_dashboard.api.setup_routes import build_setup_router
from job_dashboard.api.feedback_routes import build_feedback_router
from job_dashboard.api.hiring_routes import build_hiring_router
from job_dashboard.api.letter_routes import build_letter_router
from job_dashboard.api.qa_routes import build_qa_router
from job_dashboard.api.notification_routes import build_notification_router
from job_dashboard.api.company_routes import build_company_router
from job_dashboard.api.profile_routes import build_profile_router
from job_dashboard.api.refresh_job import RefreshState, default_pipeline_runner
from job_dashboard.api.resume_routes import build_resume_router
from job_dashboard.db import (
    dashboard_stats, distinct_classification_values, init_db, job_detail, query_jobs,
    suspected_duplicates, tracker_jobs,
)

DEFAULT_DB = str(paths.DB)


class StatusPatch(BaseModel):
    status: Optional[str] = None
    round: Optional[int] = None          # interview round, with status "interviewing"


class ApplyDetails(BaseModel):
    """Per-application facts the agent can't know; anything left unset answers No."""
    referrer: str = Field(default="", max_length=120)
    relatives: bool = False
    applied_before: bool = False
    interviewed_before: bool = False
    worked_before: bool = False


class ConfigValue(BaseModel):
    value: str = Field(default="", max_length=500)    # empty = back to the .env value / default


def create_app(
    db_path=DEFAULT_DB, pipeline_runner=None, resume_engine=None,
    resume_llm=None, jd_keyword_extractor=None, letter_engine=None,
    screening_engine=None, hiring_fetcher=None, embed_model=None, qa_embed=None,
    hiring_role_fn=None, queue_launch=None, mail_scanner=None, in_worker=False, profile_llm=None, profile_linkedin=None,
    apply_sessions=None,
):
    """``resume_llm`` overrides the default engine's ``LlmFn`` (tests inject
    a fake here to exercise the default ``resume_engine=None`` wiring
    without touching a real model). Defaults to ``make_resume_llm()``, a
    ``job_dashboard.llm`` call — building that closure does NOT touch the network
    (``make_resume_llm`` never makes an HTTP call itself); it's only
    invoked, per-keyword, from inside ``suggest_resume`` below, where every
    failure is already caught (see ``resume_llm.make_resume_llm`` and
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
    app.add_middleware(ChangeMiddleware, db_path=db_path)     # actor, confirmation gate, change log
    app.include_router(build_change_router(db_path))
    app.include_router(build_setup_router(db_path))
    app.include_router(build_apply_router(db_path, screening_engine))
    app.include_router(
        build_resume_router(db_path, resume_engine, resume_llm, jd_keyword_extractor)
    )
    app.include_router(build_letter_router(db_path, letter_engine))
    app.include_router(build_hiring_router(db_path, hiring_fetcher, embed_model, hiring_role_fn, in_worker=in_worker))
    app.include_router(build_agent_router(db_path, AgentRunState()))
    # Apply queue: the worker process runs it (job_dashboard.worker); the api only hands it start/pause through
    # jobs.db. A test's ``queue_launch`` runs it here instead, in-process, with that fake launch.
    app.state.submit_watcher = None                  # the worker watches parked forms for a hand submit
    app.state.queue_runner = (QueueRunner(str(db_path), queue_launch) if queue_launch
                              else QueueControl(db_path))
    app.include_router(build_queue_router(db_path, app.state.queue_runner))
    # Mail scan: ``mail_scanner`` overrides Gmail + the LLM (tests); the worker runs the daily loop.
    app.state.mail_scanner = mail_scanner or MailScanner(db_path)
    app.include_router(build_mail_router(db_path, app.state.mail_scanner))
    app.include_router(build_qa_router(db_path, qa_embed))
    app.include_router(build_notification_router(db_path))
    app.include_router(build_profile_router(db_path, profile_llm, profile_linkedin, qa_embed))
    app.include_router(build_feedback_router(db_path, qa_embed))
    app.include_router(build_company_router(db_path))
    # Agent-driven apply runs: the live page per job, on one browser thread (tests pass a service with a fake page).
    from job_dashboard.api.apply_session_routes import build_apply_session_router
    from job_dashboard.apply.session_actor import BrowserActor
    from job_dashboard.apply.session_service import ApplySessions
    app.state.apply_sessions = apply_sessions or ApplySessions(db_path, BrowserActor())
    app.include_router(build_apply_session_router(db_path, app.state.apply_sessions))

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
                  status: str = None, verdict: str = None, min_score: float = None,
                  include_dismissed: bool = False, sort: str = "embed",
                  limit: int = 50, offset: int = 0, india: bool = False, ids: str = None):
        id_list = [int(x) for x in (ids or "").split(",") if x.strip().isdigit()][:200] or None
        learned = sort == "learned"           # base fit + what Skip/Apply clicks taught (match/preferences.py)
        with db() as conn:
            jobs, total = query_jobs(
                conn, q=q, remote=remote, job_type=job_type, source=source,
                industry=industry, company_type=company_type,
                status=status, verdict=verdict, min_score=min_score,
                include_dismissed=include_dismissed, sort="embed" if learned else sort,
                limit=5000 if learned else limit, offset=0 if learned else offset, india=india, ids=id_list,
            )
            if learned:
                preferences.ensure(conn)
                ranked = preferences.rerank(jobs, preferences.learn(conn))
                jobs, total = ranked[offset:offset + limit], len(ranked)
        from job_dashboard.match.apply_type import classify_apply_type
        for j in jobs:
            j["apply_type"] = classify_apply_type(j.get("source"), j.get("job_url"), j.get("apply_kind"), j.get("apply_url"))
        return {"jobs": jobs, "total": total}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: int):
        with db() as conn:
            detail = job_detail(conn, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")
        from job_dashboard.match.apply_type import classify_apply_type
        detail["apply_type"] = classify_apply_type(detail.get("source"), detail.get("job_url"), detail.get("apply_kind"), detail.get("apply_url"))
        return detail

    @app.put("/api/jobs/{job_id}/apply-details")
    def put_apply_details(job_id: int, body: ApplyDetails):
        details = {**body.model_dump(), "referrer": body.referrer.strip()}
        with db() as conn:
            if conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone() is None:
                raise HTTPException(status_code=404, detail="job not found")
            changes.apply(conn, "job", job_id, "apply_details", details)
        return details

    @app.patch("/api/jobs/{job_id}/status")
    def patch_status(job_id: int, body: StatusPatch):
        with db() as conn:
            try:
                before = change_entities._job_read(conn, job_id, "status")
                set_status(conn, job_id, body.status, round=body.round)
                changes.record(conn, "job", job_id, "status", before, body.status)
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
        from job_dashboard.db import distinct_sources
        with db() as conn:
            vals = distinct_classification_values(conn)
            vals["sources"] = distinct_sources(conn)
            return vals

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/config")
    def get_config():
        return {"config": settings.listing()}

    @app.put("/api/config/{key}")
    def put_config(key: str, body: ConfigValue):
        if key not in settings.KEYS:
            raise HTTPException(status_code=404, detail=f"unknown setting {key!r}")
        with db() as conn:
            try:
                changes.apply(conn, "config", key, "value", body.value.strip() or None)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
        return {"key": key, "value": settings.get(key), "restart": settings.KEYS[key].restart}

    # In production (``in_worker``) Refresh runs in the worker process, which owns the embedding model
    # (worker_jobs.py); tests run it on a thread here with a fake pipeline.
    if in_worker:
        from job_dashboard.worker_jobs import RemoteJob
        state = RemoteJob(db_path, "refresh", idle=RefreshState().snapshot())
        state.snapshot = state.status
        start_job = lambda: state.start()                                   # noqa: E731
    else:
        state = RefreshState()
        runner = pipeline_runner or default_pipeline_runner
        start_job = lambda: state.start(lambda on_stage: runner(db_path, on_stage))   # noqa: E731

    @app.post("/api/refresh")
    def start_refresh():
        started = start_job()
        if not started:
            raise HTTPException(status_code=409, detail="refresh already running")
        return {"started": True}

    @app.get("/api/refresh/status")
    def refresh_status():
        return state.snapshot()

    # Mount frontend static files (SPA with fallback to index.html).
    # index.html (and any other non-hashed file) must never be cached without
    # revalidation — Vite's build hashes asset filenames, so a stale cached
    # index.html is the one thing that can keep serving an old bundle after a
    # rebuild. Everything under assets/ is safe to cache forever since its
    # filename changes whenever its content does.
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.is_dir():
        from fastapi.staticfiles import StaticFiles

        class _FrontendStaticFiles(StaticFiles):
            async def get_response(self, path, scope):
                response = await super().get_response(path, scope)
                if path.startswith("assets/"):
                    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                else:
                    response.headers["Cache-Control"] = "no-cache"
                return response

        app.mount("/", _FrontendStaticFiles(directory=str(dist), html=True), name="frontend")

    return app


app = create_app()
