"""Answers tab + per-application questions API.

Answers live in two stores that the agent writes together: `learned_answers`
(sqlite/FTS5, short answers) and the semantic vault (ChromaDB). This router
presents them as one list keyed by normalized question, and writes through the
agent's own MemoryRouter so the dual-write logic stays in one place. Essays are
vault-only, matching `learned_answers`' "essays are per-job" rule. Every
endpoint degrades to empty rather than 500 when the vault is unavailable.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from job_dashboard import qa_store
from job_dashboard.db import init_db

_SHORT = 200        # longer / multi-line replies are essays -> vault only


class AnswerBody(BaseModel):
    question: str
    answer: str
    purpose: Optional[str] = None


class ReplyBody(BaseModel):
    answer: str


class ReviewBody(BaseModel):
    verdict: str                       # "correct" | "wrong"
    answer: Optional[str] = None       # the right answer, when wrong


class SettingsBody(BaseModel):
    answer_confidence_min: int


def build_qa_router(db_path, vault=None) -> APIRouter:
    router = APIRouter()
    state = {"vault": vault}

    def get_vault():
        if state["vault"] is None:
            try:
                from career_agent.memory.semantic_behavior import SemanticBehaviorVault
                state["vault"] = SemanticBehaviorVault(
                    persist_dir=str(Path(db_path).parent / "semantic_behavior"))
            except Exception:
                return None
        return state["vault"]

    def db():
        # Both tables are otherwise created lazily by the agent, so a fresh
        # database (no run yet) would 500 here instead of showing "nothing yet".
        conn = init_db(db_path)
        qa_store.ensure(conn)
        from career_agent.memory.learned_answers import ensure as ensure_learned
        ensure_learned(conn)
        return conn

    def learned_rows(conn):
        cur = conn.execute("SELECT qkey, label, answer, purpose, updated_at FROM learned_answers")
        return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]

    def teach(conn, question, answer, purpose=None, essay=False):
        """Save to memory. Short answers go to both stores via the agent's
        RECORD_FEEDBACK (an 'edit' — it resets vault confidence, existing rule);
        essays only to the vault."""
        v = get_vault()
        if essay or len(answer) > _SHORT or "\n" in answer:
            if v is not None:
                v.record_feedback(question, answer, "edit")
            return
        from career_agent.memory.learned_answers import AnswerMemory
        from career_agent.routers.memory_router import MemoryRouter
        if v is None:                      # vault down: keep the FTS half working
            from career_agent.browser.form_model import Field
            AnswerMemory(conn).record(Field("_dash", "text", question, False, [], None, purpose), answer)
            return
        MemoryRouter(profile={}, exact_tech=None, semantic=v, answer_memory=AnswerMemory(conn)
                     ).dispatch("RECORD_FEEDBACK", {"question": question, "answer": answer,
                                                    "event": "edit", "purpose": purpose})

    @router.get("/api/answers")
    def list_answers(q: str = ""):
        conn = db()
        try:
            asked = qa_store.asked_in_counts(conn)
            merged: dict[str, dict] = {}
            for r in learned_rows(conn):
                merged[r["qkey"]] = {"qkey": r["qkey"], "question": r["label"], "answer": r["answer"],
                                     "purpose": r["purpose"], "updated_at": r["updated_at"],
                                     "in_learned": True, "in_vault": False,
                                     "confidence": None, "approved_count": None, "autonomous": False}
            v = get_vault()
            try:
                entries = v.list_all() if v is not None else []
            except Exception:
                entries = []
            for e in entries:
                k = qa_store.norm_key(e["question"])
                m = merged.setdefault(k, {"qkey": k, "question": e["question"], "answer": e.get("answer"),
                                          "purpose": None, "updated_at": None, "in_learned": False})
                m.update(in_vault=True, confidence=e.get("confidence"),
                         approved_count=e.get("approved_count"),
                         autonomous=(e.get("confidence") or 0) >= 1.0)
                m.setdefault("answer", e.get("answer"))
            out = [dict(m, asked_in=asked.get(k, 0)) for k, m in merged.items()]
        finally:
            conn.close()
        needle = q.strip().lower()
        if needle:
            out = [a for a in out if needle in (a["question"] or "").lower()
                   or needle in (a["answer"] or "").lower()]
        return {"answers": sorted(out, key=lambda a: (a["updated_at"] or ""), reverse=True)}

    @router.put("/api/answers")
    def upsert_answer(body: AnswerBody):
        if not body.question.strip() or not body.answer.strip():
            raise HTTPException(status_code=422, detail="question and answer are required")
        conn = db()
        try:
            teach(conn, body.question.strip(), body.answer.strip(), body.purpose)
        finally:
            conn.close()
        return {"ok": True, "qkey": qa_store.norm_key(body.question)}

    @router.delete("/api/answers")
    def delete_answer(qkey: str):
        conn = db()
        try:
            cur = conn.execute("DELETE FROM learned_answers WHERE qkey=?", (qkey,))
            conn.execute("DELETE FROM learned_answers_fts WHERE qkey=?", (qkey,))
            conn.commit()
            removed = {"learned": cur.rowcount > 0, "vault": False}
            v = get_vault()
            if v is not None:
                for e in v.list_all():
                    if qa_store.norm_key(e["question"]) == qkey:
                        v.delete(e["question"])
                        removed["vault"] = True
        finally:
            conn.close()
        if not any(removed.values()):
            raise HTTPException(status_code=404, detail="no such answer")
        return {"ok": True, "removed": removed}

    @router.get("/api/answers/applications")
    def answer_applications(qkey: str):
        conn = db()
        try:
            return {"applications": qa_store.applications_for(conn, qkey)}
        finally:
            conn.close()

    @router.get("/api/jobs/{job_id}/questions")
    def job_questions(job_id: int):
        conn = db()
        try:
            return {"questions": qa_store.open_questions(conn, job_id)}
        finally:
            conn.close()

    @router.get("/api/questions/open-counts")
    def open_counts():
        conn = db()
        try:
            return {str(j): n for j, n in qa_store.open_counts(conn).items()}
        finally:
            conn.close()

    @router.post("/api/jobs/{job_id}/questions/{row_id}/reply")
    def reply(job_id: int, row_id: int, body: ReplyBody):
        if not body.answer.strip():
            raise HTTPException(status_code=422, detail="answer is required")
        conn = db()
        try:
            row = conn.execute("SELECT label, kind, purpose FROM application_qa "
                               "WHERE id=? AND job_id=?", (row_id, job_id)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="question not found")
            label, kind, purpose = row
            teach(conn, label, body.answer.strip(), purpose, essay=(kind == "textarea"))
            qa_store.mark_answered(conn, job_id, qa_store.norm_key(label), body.answer.strip())
        finally:
            conn.close()
        return {"ok": True}

    @router.get("/api/jobs/{job_id}/answers-used")
    def answers_used(job_id: int):
        conn = db()
        try:
            return {"answers": qa_store.answers_used(conn, job_id)}
        finally:
            conn.close()

    @router.post("/api/application-qa/{row_id}/review")
    def review(row_id: int, body: ReviewBody):
        """Mark a filled answer correct/wrong. Wrong + a corrected answer also
        teaches memory, so the bad entry is replaced, not just flagged."""
        if body.verdict not in ("correct", "wrong"):
            raise HTTPException(status_code=422, detail="verdict must be correct or wrong")
        conn = db()
        try:
            row = conn.execute("SELECT label, kind, purpose FROM application_qa WHERE id=?", (row_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="not found")
            if body.verdict == "wrong" and (body.answer or "").strip():
                teach(conn, row[0], body.answer.strip(), row[2], essay=(row[1] == "textarea"))
            qa_store.set_outcome(conn, row_id, "kept" if body.verdict == "correct" else "edited")
        finally:
            conn.close()
        return {"ok": True}

    @router.get("/api/retrieval/stats")
    def retrieval_stats():
        conn = db()
        try:
            return qa_store.retrieval_stats(conn)
        finally:
            conn.close()

    @router.get("/api/retrieval/recent")
    def retrieval_recent(limit: int = 50):
        conn = db()
        try:
            return {"recent": qa_store.recent_retrievals(conn, limit)}
        finally:
            conn.close()

    @router.get("/api/agent-settings")
    def get_settings():
        conn = db()
        try:
            return {"answer_confidence_min": qa_store.confidence_min(conn)}
        finally:
            conn.close()

    @router.put("/api/agent-settings")
    def put_settings(body: SettingsBody):
        if not 0 <= body.answer_confidence_min <= 100:
            raise HTTPException(status_code=422, detail="must be 0-100")
        conn = db()
        try:
            qa_store.set_setting(conn, "answer_confidence_min", body.answer_confidence_min)
        finally:
            conn.close()
        return {"answer_confidence_min": body.answer_confidence_min}

    @router.get("/api/ingredients")
    def ingredients():
        """Read-only: the verbatim-source bank is edited in the file, never here."""
        p = Path(db_path).parent / "answer_style" / "ingredients.json"
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            return {"units": [], "skills_pool": []}
        return {"units": [{k: u.get(k) for k in ("id", "type", "title", "org", "tags")}
                           for u in d.get("units", [])],
                "skills_pool": d.get("skills_pool", [])}

    return router
