import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from job_dashboard.api.refresh_job import RefreshState, default_pipeline_runner
from job_dashboard.db import (
    dashboard_stats, init_db, job_detail, query_jobs, set_job_status,
    suspected_duplicates,
)

DEFAULT_DB = "data/jobs.db"


class StatusPatch(BaseModel):
    status: Optional[str] = None


def create_app(db_path=DEFAULT_DB, pipeline_runner=None):
    app = FastAPI(title="Job Dashboard")

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

    return app


app = create_app()
