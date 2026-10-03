"""Questionnaire (question bank) + per-application questions API.

The questionnaire is the agent's question bank (career_agent.memory.qbank):
one entry per canonical question, answered once here. Per-application rows
come from application_qa. The bank grows only from choices made here: a reply
becomes a new entry, another wording of an entry, or stays one-off; a review
confirms a wording or re-points it to the right entry. Spec 2026-09-26 §3–4.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from career_agent.memory import qbank
from career_agent.memory.qbank_match import split_escape
from career_agent.memory.qbank_rules import NO_INPUT_RULES, RULE_HELP
from job_dashboard import qa_store
from job_dashboard.apply.store import get_application_profile
from job_dashboard.db import init_db
from job_dashboard.sources.cdp import state as cdp_state


class AnswerBody(BaseModel):
    answer: str
    entry_id: Optional[str] = None     # answer an existing entry
    question: Optional[str] = None     # or create a new one


class ReplyBody(BaseModel):
    answer: str
    save_as: str = "once"              # "once" | "new" | "wording"
    entry_id: Optional[str] = None     # required for "wording"


class ReviewBody(BaseModel):
    verdict: str                       # "correct" | "wrong"
    entry_id: Optional[str] = None     # wrong: the entry this question really is


class SettingsBody(BaseModel):
    answer_confidence_min: Optional[int] = None
    qbank_confident_min: Optional[int] = None
    browser_linkedin_enabled: Optional[bool] = None
    browser_naukri_enabled: Optional[bool] = None
    browser_wellfound_enabled: Optional[bool] = None
    browser_instahyre_enabled: Optional[bool] = None
    browser_iimjobs_enabled: Optional[bool] = None
    browser_indeed_enabled: Optional[bool] = None
    browser_ycstartups_enabled: Optional[bool] = None


BROWSER_SITES = ("linkedin", "naukri", "wellfound", "instahyre", "iimjobs", "indeed", "ycstartups")


def _browser_flags(conn) -> dict:
    return {f"browser_{s}_enabled": qa_store.get_setting(conn, f"browser_{s}_enabled") == "1" for s in BROWSER_SITES}


def _requeue_if_unblocked(conn, job_id: int) -> bool:
    """A job the apply queue parked or failed goes back to the end of the queue
    once its last open question is answered — the bank now has the answers."""
    from job_dashboard.apply import queue as apply_queue
    row = conn.execute("SELECT state FROM apply_queue WHERE job_id = ?", (job_id,)).fetchone()
    if row is None or row[0] not in ("parked", "failed") or qa_store.open_questions(conn, job_id):
        return False
    apply_queue.enqueue(conn, job_id)
    from job_dashboard.db import set_job_status
    set_job_status(conn, job_id, "saved")          # Failed -> Queued on the tracker
    return True


def build_qa_router(db_path, embed=None) -> APIRouter:
    router = APIRouter()

    def get_embed():
        return embed or qbank.default_embed

    def db():
        conn = init_db(db_path)
        qa_store.ensure(conn)
        qbank.seed_if_empty(conn, get_embed())
        return conn

    def view(conn, e, asked, profile) -> dict:
        words = qbank.wordings_for(conn, e["id"])
        raw = profile.get(e["profile_ref"]) if e["profile_ref"] else e["answer"]
        value = None if raw is None or str(raw).strip() == "" else str(raw)
        return {"id": e["id"], "question": e["question"], "topic": e["topic"], "atype": e["atype"],
                "answer": e["answer"], "profile_ref": e["profile_ref"], "rule": e["rule"],
                "rule_help": RULE_HELP.get(e["rule"]), "value": value,
                "needs_input": not e["profile_ref"] and e["rule"] not in NO_INPUT_RULES,
                "wordings": words, "updated_at": e["updated_at"],
                "asked_in": sum(asked.get(qa_store.norm_key(w), 0) for w in words)}

    def link(conn, label, entry_id, source, replace):
        q = split_escape(label)[0] or label
        qbank.add_wording(conn, q, entry_id, get_embed()([q])[0], source, replace=replace)

    @router.get("/api/answers")
    def list_answers(q: str = ""):
        conn = db()
        try:
            asked = qa_store.asked_in_counts(conn)
            profile = get_application_profile(conn) or {}
            out = [view(conn, e, asked, profile) for e in qbank.entries(conn)]
        finally:
            conn.close()
        needle = q.strip().lower()
        if needle:
            out = [a for a in out if needle in a["question"].lower() or needle in (a["value"] or "").lower()
                   or any(needle in w.lower() for w in a["wordings"])]
        return {"answers": out,
                "unanswered": sum(1 for a in out if a["needs_input"] and a["value"] is None)}

    @router.put("/api/answers")
    def upsert_answer(body: AnswerBody):
        ans = body.answer.strip()
        if not ans:
            raise HTTPException(status_code=422, detail="answer is required")
        conn = db()
        try:
            if body.entry_id:
                if not qbank.set_answer(conn, body.entry_id, ans):
                    raise HTTPException(status_code=404, detail="no such entry")
                eid = body.entry_id
            elif (body.question or "").strip():
                eid = qbank.add_entry(conn, question=body.question.strip(), kind="text",
                                      answer=ans, embed=get_embed())
            else:
                raise HTTPException(status_code=422, detail="entry_id or question is required")
        finally:
            conn.close()
        return {"ok": True, "id": eid}

    @router.delete("/api/answers")
    def delete_answer(entry_id: str):
        """Retire, don't erase: the entry stays in the DB as superseded."""
        conn = db()
        try:
            if not qbank.set_status(conn, entry_id, "superseded"):
                raise HTTPException(status_code=404, detail="no such entry")
        finally:
            conn.close()
        return {"ok": True}

    @router.get("/api/qbank/entries")
    def qbank_entries(search: str = ""):
        conn = db()
        try:
            n = search.strip().lower()
            return {"entries": [{"id": e["id"], "question": e["question"], "topic": e["topic"]}
                                for e in qbank.entries(conn)
                                if e["topic"] != "story" and (not n or n in e["question"].lower() or n in e["id"])]}
        finally:
            conn.close()

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
            asked = qa_store.asked_in_counts(conn)
            return {"questions": [dict(q, asked_in=asked.get(q["qkey"], 0))
                                  for q in qa_store.open_questions(conn, job_id)]}
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
        ans = body.answer.strip()
        if not ans:
            raise HTTPException(status_code=422, detail="answer is required")
        if body.save_as not in ("once", "new", "wording"):
            raise HTTPException(status_code=422, detail="save_as must be once, new or wording")
        conn = db()
        try:
            row = conn.execute("SELECT label, kind, source, answer FROM application_qa WHERE id=? AND job_id=?",
                               (row_id, job_id)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="question not found")
            label, kind, source, prior_answer = row
            if body.save_as == "new":
                qbank.add_entry(conn, question=split_escape(label)[0] or label, kind=kind,
                                answer=ans, embed=get_embed())
            elif body.save_as == "wording":
                if not body.entry_id or qbank.get_entry(conn, body.entry_id) is None:
                    raise HTTPException(status_code=422, detail="pick an existing entry")
                link(conn, label, body.entry_id, "human", replace=True)
            keep_source = source == "qbank_likely"
            if keep_source:
                same = (prior_answer or "").strip().casefold() == ans.casefold()
                qa_store.set_outcome(conn, row_id, "kept" if same else "edited")
            qa_store.mark_answered(conn, job_id, qa_store.norm_key(label), ans, keep_source=keep_source)
            requeued = _requeue_if_unblocked(conn, job_id)
        finally:
            conn.close()
        return {"ok": True, "requeued": requeued}

    @router.get("/api/jobs/{job_id}/answers-used")
    def answers_used(job_id: int):
        conn = db()
        try:
            return {"answers": qa_store.answers_used(conn, job_id)}
        finally:
            conn.close()

    @router.post("/api/application-qa/{row_id}/review")
    def review(row_id: int, body: ReviewBody):
        """Correct: a similar-wording match becomes an exact wording of its entry.
        Wrong + entry_id: this wording is re-pointed to the entry it really is."""
        if body.verdict not in ("correct", "wrong"):
            raise HTTPException(status_code=422, detail="verdict must be correct or wrong")
        conn = db()
        try:
            row = conn.execute("SELECT label, retrieved_qkey, retrieval_kind FROM application_qa WHERE id=?",
                               (row_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="not found")
            label, matched, kind = row
            if body.verdict == "correct":
                if matched and kind in ("shortlist", "llm") and qbank.get_entry(conn, matched):
                    link(conn, label, matched, "kept", replace=False)
            elif body.entry_id:
                if qbank.get_entry(conn, body.entry_id) is None:
                    raise HTTPException(status_code=422, detail="no such entry")
                link(conn, label, body.entry_id, "human", replace=True)
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
            return {"answer_confidence_min": qa_store.confidence_min(conn),
                    "qbank_confident_min": qa_store.qbank_confident_min(conn),
                    **_browser_flags(conn),
                    "browser_min_interval_hours": cdp_state.interval_hours(conn)}
        finally:
            conn.close()

    @router.put("/api/agent-settings")
    def put_settings(body: SettingsBody):
        for key in ("answer_confidence_min", "qbank_confident_min"):
            v = getattr(body, key)
            if v is not None and not 0 <= v <= 100:
                raise HTTPException(status_code=422, detail=f"{key} must be 0-100")
        conn = db()
        try:
            for key in ("answer_confidence_min", "qbank_confident_min"):
                if getattr(body, key) is not None:
                    qa_store.set_setting(conn, key, getattr(body, key))
            for site in BROWSER_SITES:
                val = getattr(body, f"browser_{site}_enabled")
                if val is not None:
                    qa_store.set_setting(conn, f"browser_{site}_enabled", "1" if val else "0")
            return {"answer_confidence_min": qa_store.confidence_min(conn),
                    "qbank_confident_min": qa_store.qbank_confident_min(conn),
                    **_browser_flags(conn)}
        finally:
            conn.close()

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
