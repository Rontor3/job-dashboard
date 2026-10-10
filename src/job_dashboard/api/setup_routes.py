"""Onboarding data the in-app agent works with: secrets, the résumé, the candidate profile, the setup state.

GET  /api/secrets                which keys are set (never a value)
PUT  /api/secrets/{KEY}          write one value to .env — the dashboard's secure input only (agent refused)
PUT  /api/current-resume         a PDF body becomes <data>/current_resume.pdf — the upload widget only
GET  /api/current-resume/text    the résumé's text, for the agent to read
GET/PUT /api/candidate-profile   the candidate profile .local.md (full text, logged with Undo)
GET/PUT /api/setup-state         data/setup-state.md (logged with Undo)
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from job_dashboard import change_entities, changes, paths
from job_dashboard.db import init_db

SECRET_KEYS = ("LLM_API_KEY", "TINYFISH_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
               "CAREER_AGENT_EMAIL", "CAREER_AGENT_FIRST_NAME", "CAREER_AGENT_LAST_NAME")
ENV_PATH = Path(os.getenv("JOB_DASHBOARD_ENV_FILE") or paths.REPO_ROOT / ".env")   # tests point this elsewhere
MAX_RESUME_BYTES = 10 * 1024 * 1024


class SecretBody(BaseModel):
    value: str = Field(min_length=1, max_length=4000)


class TextBody(BaseModel):
    text: str = Field(max_length=200_000)


def _env_lines() -> list[str]:
    return ENV_PATH.read_text().splitlines() if ENV_PATH.is_file() else []


def secret_present(key: str) -> bool:
    for line in _env_lines():
        k, sep, v = line.strip().removeprefix("export ").partition("=")
        if sep and k.strip() == key:
            return bool(v.strip().strip("'\""))
    return bool(os.getenv(key))


def write_secret(key: str, value: str) -> None:
    """Replace or append ``KEY=value`` in .env, atomically, keeping every other line."""
    if "\n" in value or "\r" in value:
        raise ValueError("value must be one line")
    quoted = f'"{value}"' if re.search(r"\s|#|'|\"", value) else value
    lines, done = _env_lines(), False
    for i, line in enumerate(lines):
        k, sep, _ = line.strip().removeprefix("export ").partition("=")
        if sep and k.strip() == key:
            lines[i], done = f"{key}={quoted}", True
    if not done:
        lines.append(f"{key}={quoted}")
    tmp = ENV_PATH.with_name(".env.tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(ENV_PATH)
    os.environ[key] = value                     # this process uses it at once; the others on their next read/restart


def _setup_status(text: Optional[str]) -> Optional[str]:
    m = re.search(r"^status:\s*(\w+)", text or "", re.M)
    return m.group(1) if m else None


def build_setup_router(db_path) -> APIRouter:
    router = APIRouter()

    def db():
        conn = init_db(db_path)
        changes.ensure(conn)
        return conn

    @router.get("/api/secrets")
    def list_secrets():
        return {"secrets": {k: secret_present(k) for k in SECRET_KEYS}}

    @router.put("/api/secrets/{key}")
    def put_secret(key: str, body: SecretBody):
        if key not in SECRET_KEYS:
            raise HTTPException(status_code=404, detail=f"unknown secret {key!r}")
        try:
            write_secret(key, body.value.strip())
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        conn = db()
        try:
            changes.record(conn, "secret", key, "value", None, "set", undoable=False)   # never the value
        finally:
            conn.close()
        return {"key": key, "set": True}

    @router.put("/api/current-resume")
    async def put_resume(request: Request):
        data = await request.body()
        if not data.startswith(b"%PDF"):
            raise HTTPException(status_code=422, detail="that isn't a PDF")
        if len(data) > MAX_RESUME_BYTES:
            raise HTTPException(status_code=413, detail="the PDF is over 10 MB")
        from job_dashboard.match.profile_text import current_resume_pdf
        target = Path(current_resume_pdf())
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
        conn = db()
        try:
            changes.record(conn, "file", "current_resume", "upload", None, f"{len(data)} bytes", undoable=False)
        finally:
            conn.close()
        return {"uploaded": True, "bytes": len(data)}

    @router.get("/api/current-resume/text")
    def resume_text():
        from job_dashboard.match.profile_text import current_resume_pdf
        from job_dashboard.resume.ats import _default_extract
        pdf = Path(current_resume_pdf())
        if not pdf.is_file():
            raise HTTPException(status_code=404, detail="no résumé uploaded yet")
        try:
            return {"text": _default_extract(pdf)}
        except Exception as e:  # noqa: BLE001 — pdftotext missing or a broken PDF
            raise HTTPException(status_code=422, detail=f"couldn't read the PDF ({type(e).__name__})")

    def text_routes(route: str, name: str):
        @router.get(route, name=f"get_{name}")
        def get_text():
            text = change_entities.read_file(name)
            out = {"exists": text is not None, "text": text or ""}
            return {**out, "status": _setup_status(text)} if name == "setup_state" else out

        @router.put(route, name=f"put_{name}")
        def put_text(body: TextBody):
            conn = db()
            try:
                changes.apply(conn, "file", name, "text", body.text)
            finally:
                conn.close()
            return {"exists": True, "text": body.text}

    text_routes("/api/candidate-profile", "candidate_profile")
    text_routes("/api/setup-state", "setup_state")
    return router
