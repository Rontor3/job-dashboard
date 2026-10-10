"""Profile readiness, filling it from what the user already gave us, and reading typed answers (profile_intel.py).

    GET  /api/profile/readiness      {percent, ready, required_missing, optional_missing, autofill_due}
    POST /api/profile/autofill       {linkedin?}: read the résumé, candidate profile, essay bank (and LinkedIn) into
                                     the gaps → {filled, sources, readiness}
    POST /api/profile/facts          {answers: {key: value}}: save several at once (logged, with Undo)
    POST /api/answers/interpret      {question, text, entry_id?, choices?} → {answer, also, request}; saves nothing
    POST /api/inbox/snooze           {keys, days?}: stop showing these Inbox items for a while (Skip)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from job_dashboard import profile_intel, qa_store
from job_dashboard.db import init_db


class AutofillBody(BaseModel):
    linkedin: bool = True


class FactsBody(BaseModel):
    answers: dict[str, Optional[str]] = Field(max_length=60)


class InterpretBody(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=4000)
    entry_id: Optional[str] = None
    choices: Optional[list[str]] = Field(default=None, max_length=40)


class SnoozeBody(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=100)
    days: int = Field(default=30, ge=1, le=365)


def snoozed(conn) -> set[str]:
    """Inbox keys still snoozed now."""
    try:
        table = json.loads(qa_store.get_setting(conn, "inbox_snoozed") or "{}")
    except ValueError:
        return set()
    now = datetime.now(timezone.utc).isoformat()
    return {k for k, until in table.items() if until > now}


def _documents(conn, linkedin: bool, read_linkedin) -> dict[str, str]:
    from job_dashboard import change_entities
    from job_dashboard.match.profile_text import current_resume_pdf
    docs: dict[str, str] = {}
    pdf = Path(current_resume_pdf())
    if pdf.is_file():
        from job_dashboard.resume.ats import _default_extract
        try:
            docs["Résumé"] = _default_extract(pdf)
        except Exception:                                          # noqa: BLE001 — unreadable PDF: other sources
            pass
    docs["Candidate profile"] = change_entities.read_file("candidate_profile") or ""
    ing = change_entities.read_file("ingredients")
    if ing:
        try:
            units = json.loads(ing).get("units", [])
            docs["Projects and roles"] = "\n".join(f"- {u.get('title')}: {u.get('source', '')}" for u in units)
        except ValueError:
            pass
    if linkedin and qa_store.get_setting(conn, "browser_linkedin_enabled") == "1":
        docs["LinkedIn profile"] = read_linkedin()
    return docs


def build_profile_router(db_path, llm=None, read_linkedin=None, embed=None) -> APIRouter:
    router = APIRouter()

    def model(prompt):
        if llm is not None:
            return llm(prompt)
        from job_dashboard.llm import complete_json
        return complete_json(prompt)

    def linkedin_text():
        if read_linkedin is not None:
            return read_linkedin()
        from job_dashboard.linkedin.own_profile import read
        return read()

    def db():
        from career_agent.memory import qbank
        conn = init_db(db_path)
        qa_store.ensure(conn)
        qbank.seed_if_empty(conn, embed or qbank.default_embed)
        return conn

    def due(conn) -> bool:
        from job_dashboard.match.profile_text import current_resume_pdf
        pdf = Path(current_resume_pdf())
        last = qa_store.get_setting(conn, "profile_autofill_at")
        if not pdf.is_file():
            return False
        if not last:
            return True
        return datetime.fromtimestamp(pdf.stat().st_mtime, timezone.utc).isoformat() > last

    @router.get("/api/profile/readiness")
    def get_readiness():
        conn = db()
        try:
            return {**profile_intel.readiness(conn), "autofill_due": due(conn),
                    "autofill_at": qa_store.get_setting(conn, "profile_autofill_at") or None}
        finally:
            conn.close()

    @router.post("/api/profile/autofill")
    def post_autofill(body: AutofillBody):
        conn = db()
        try:
            docs = _documents(conn, body.linkedin, linkedin_text)
            try:
                out = profile_intel.autofill(conn, docs, model)
            except Exception as e:                                 # noqa: BLE001 — the model is down or odd
                raise HTTPException(status_code=502, detail=f"couldn't read your documents ({type(e).__name__})")
            return {**out, "readiness": profile_intel.readiness(conn)}
        finally:
            conn.close()

    @router.post("/api/profile/facts")
    def post_facts(body: FactsBody):
        conn = db()
        try:
            return {"written": profile_intel.write(conn, body.answers), "readiness": profile_intel.readiness(conn)}
        finally:
            conn.close()

    @router.post("/api/answers/interpret")
    def post_interpret(body: InterpretBody):
        conn = db()
        try:
            return profile_intel.interpret(conn, body.question, body.text, model, body.choices, body.entry_id)
        finally:
            conn.close()

    @router.post("/api/inbox/snooze")
    def post_snooze(body: SnoozeBody):
        conn = db()
        try:
            try:
                table = json.loads(qa_store.get_setting(conn, "inbox_snoozed") or "{}")
            except ValueError:
                table = {}
            until = (datetime.now(timezone.utc) + timedelta(days=body.days)).isoformat()
            table.update({k: until for k in body.keys})
            now = datetime.now(timezone.utc).isoformat()
            qa_store.set_setting(conn, "inbox_snoozed", json.dumps({k: v for k, v in table.items() if v > now}))
            return {"snoozed": len(body.keys), "until": until}
        finally:
            conn.close()

    return router
