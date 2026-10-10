"""The feedback surface: everything the agent needs from the human, and every click that teaches it.

GET  /api/inbox                    open questions blocking applications, guesses to confirm, top unanswered bank entries
POST /api/jobs/{id}/feedback       Skip (with reasons) / More-like-this — re-ranks the feed and the LLM fit-judge
GET  /api/preferences              what the clicks taught (likes, dislikes, blocked companies) + skip reasons
DELETE /api/preferences/{feature}  forget one learned preference
POST /api/explain                  plain-language meaning of a form question (the "What does this mean?" link)
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from career_agent.memory import qbank
from career_agent.memory.qbank_rules import NO_INPUT_RULES, RULE_HELP
from job_dashboard import llm as llm_client
from job_dashboard import qa_store
from job_dashboard.apply.store import get_application_profile
from job_dashboard.db import init_db, set_job_status
from job_dashboard.match import preferences

_GUESS_SOURCES = ("qbank_likely", "judgment", "semantic", "learned")


class FeedbackBody(BaseModel):
    verdict: str
    reasons: list[str] = []


class ExplainBody(BaseModel):
    question: str
    options: list[str] = []
    company: str | None = None


def _explain_prompt(b: ExplainBody) -> str:
    opts = f" The choices are: {', '.join(b.options)}." if b.options else ""
    who = f" from {b.company}" if b.company else ""
    return (f'A job application form{who} asks the candidate: "{b.question.strip()}".{opts}\n'
            "In at most 3 short, plain sentences, explain what the employer is actually asking, why they ask it, "
            "and what each choice would mean for the candidate. No preamble, no advice on which to pick.")


def _questions(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT a.id, a.job_id, j.title, j.company, a.label, a.kind, a.answer, a.source, a.context_json
           FROM application_qa a JOIN jobs j ON j.id = a.job_id
           WHERE a.status = 'needs_answer'
             AND a.id = (SELECT MAX(id) FROM application_qa b WHERE b.job_id = a.job_id AND b.qkey = a.qkey)
           ORDER BY a.job_id, a.id""").fetchall()
    out = []
    for rid, jid, title, company, label, kind, answer, source, ctx in rows:
        try:
            options = (json.loads(ctx) or {}).get("options") or [] if ctx else []
        except (ValueError, AttributeError):
            options = []
        out.append({"row_id": rid, "job_id": jid, "title": title, "company": company, "label": label,
                    "kind": kind, "options": options, "guess": answer if source == "qbank_likely" else None})
    return out


def _guesses(conn, limit: int = 20) -> list[dict]:
    marks = ",".join("?" * len(_GUESS_SOURCES))
    rows = conn.execute(
        f"""SELECT a.id, a.job_id, j.title, j.company, a.label, a.answer, a.source, a.confidence, a.retrieved_qkey
            FROM application_qa a JOIN jobs j ON j.id = a.job_id
            WHERE a.status = 'filled' AND a.outcome IS NULL AND a.source IN ({marks})
              AND a.answer IS NOT NULL AND TRIM(a.answer) != ''
            ORDER BY a.id DESC LIMIT ?""", (*_GUESS_SOURCES, limit)).fetchall()
    keys = ("row_id", "job_id", "title", "company", "label", "answer", "source", "confidence", "matched")
    return [dict(zip(keys, r)) for r in rows]


def _bank(conn, limit: int) -> list[dict]:
    asked = qa_store.asked_in_counts(conn)
    profile = get_application_profile(conn) or {}
    todo = []
    for e in qbank.entries(conn):
        if e["profile_ref"] or e["rule"] in NO_INPUT_RULES or e["topic"] == "story":
            continue
        if (e["answer"] or "").strip() or (profile.get(e["profile_ref"]) if e["profile_ref"] else None):
            continue
        keys = [qa_store.norm_key(w) for w in qbank.wordings_for(conn, e["id"])]
        n = sum(asked.get(k, 0) for k in keys)
        asked_by = list(dict.fromkeys(a["company"] for k in keys if asked.get(k)
                                      for a in qa_store.applications_for(conn, k) if a["company"]))[:3]
        todo.append({"id": e["id"], "question": e["question"], "atype": e["atype"], "asked_in": n,
                     "asked_by": asked_by, "rule": e["rule"], "rule_help": RULE_HELP.get(e["rule"])})
    todo.sort(key=lambda e: -e["asked_in"])
    return todo[:limit]


def build_feedback_router(db_path, embed=None) -> APIRouter:
    router = APIRouter()

    def db():
        conn = init_db(db_path)
        qa_store.ensure(conn)
        preferences.ensure(conn)
        qbank.seed_if_empty(conn, embed or qbank.default_embed)
        return conn

    @router.get("/api/inbox")
    def inbox(bank_limit: int = 5):
        conn = db()
        try:
            return {"questions": _questions(conn), "guesses": _guesses(conn),
                    "bank": _bank(conn, max(0, min(bank_limit, 50)))}
        finally:
            conn.close()

    @router.post("/api/jobs/{job_id}/feedback")
    def feedback(job_id: int, body: FeedbackBody):
        conn = db()
        try:
            if conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone() is None:
                raise HTTPException(status_code=404, detail="job not found")
            try:
                preferences.record(conn, job_id, body.verdict, body.reasons)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))
            if body.verdict == "skip":
                set_job_status(conn, job_id, "dismissed")
            return preferences.summary(preferences.learn(conn))
        finally:
            conn.close()

    @router.post("/api/explain")
    def explain(body: ExplainBody):
        if not body.question.strip():
            raise HTTPException(status_code=422, detail="question is required")
        try:
            text = llm_client.complete(_explain_prompt(body), temperature=0.2).strip()
        except Exception as e:  # noqa: BLE001 — model down / misconfigured
            raise HTTPException(status_code=503, detail=f"the model couldn't be reached ({type(e).__name__})")
        return {"explanation": text}

    @router.get("/api/preferences")
    def get_preferences():
        conn = db()
        try:
            return {**preferences.summary(preferences.learn(conn)),
                    "skip_reasons": [{"key": k, "label": v} for k, v in preferences.SKIP_REASONS.items()]}
        finally:
            conn.close()

    @router.delete("/api/preferences/{feature:path}")
    def forget(feature: str):
        conn = db()
        try:
            preferences.mute(conn, feature)
            return preferences.summary(preferences.learn(conn))
        finally:
            conn.close()

    return router
