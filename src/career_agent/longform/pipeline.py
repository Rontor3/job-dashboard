"""plan -> retrieve -> write -> verify. Same return shape as draft_screening_answer (plus how the answer was built),
so judgment.py can use either. Never raises."""
from __future__ import annotations

import json

from job_dashboard.apply.screening import _facts_block, _general_answer
from job_dashboard.letter.grounding import check_grounding

from .kb import KnowledgeBase
from .needs import plan_needs
from .recipes import retrieve
from .verify import fit_length, leak_check
from .write import draft


def _company_text(research) -> str:
    block = _facts_block(research)
    return "" if block.strip() == "(none)" else block


def answer_longform(question, *, job, kb, llm, research=None, limit=None, prior=None) -> dict:
    jd = (job.get("description") if isinstance(job, dict) else "") or ""
    plan = plan_needs(question, jd, kb, llm, prior)
    chunks = retrieve(plan, kb, question=question, jd_text=jd, company_text=_company_text(research))
    flags: list[str] = []

    out = draft(question, chunks, job, llm, limit)
    answer = out["answer"]
    if answer is not None:
        leaks = leak_check(answer, chunks, kb)
        if leaks:                                    # one redraft, naming what to leave out
            names = tuple(kb.units[p]["title"] for p in leaks)
            retry = draft(question, chunks, job, llm, limit, avoid=names)
            if retry["answer"]:
                out, answer = retry, retry["answer"]
                leaks = leak_check(answer, chunks, kb)
            if leaks:
                flags.append("project_leak:" + ",".join(leaks))
    if answer is not None and not out.get("parsed"):
        flags.append("unparsed_reply")
    if answer is None:
        answer = _general_answer(job, " ".join(c.text for c in chunks))
        flags.append("general_fallback")
    answer, trimmed = fit_length(answer, limit)
    if trimmed:
        flags.append("trimmed_to_limit")

    try:
        job_text = " ".join(str(job.get(k) or "") for k in ("title", "company", "description")) if isinstance(job, dict) else ""
        unsupported = check_grounding(answer, research, "\n".join(c.text for c in chunks), job_text).unsupported_company_claims
    except Exception:
        unsupported = []
    return {"answer": answer, "flags": flags, "unsupported_company_claims": unsupported,
            "confidence": out["confidence"], "basis": out["basis"], "prompt": out["prompt"],
            "needs": list(plan.needs), "project_id": plan.project_id, "used": [c.id for c in chunks]}


def prior_project(conn, job_id, label) -> str | None:
    """The project recorded for this job's earlier draft of this question (the user's override sticks)."""
    try:
        row = conn.execute("SELECT context_json FROM application_qa WHERE job_id=? AND label=? "
                           "AND context_json LIKE '%project_id%' ORDER BY id DESC LIMIT 1", (job_id, label)).fetchone()
        return (json.loads(row[0]) if row and row[0] else {}).get("project_id")
    except Exception:
        return None


def make_longform(conn, job, contact, llm, research, ingredients_path):
    """The callable judgment.py uses: run(question, field) -> result dict. The knowledge base is loaded once."""
    kb = KnowledgeBase.load(conn, ingredients_path, contact)

    def run(question, field=None):
        prior = prior_project(conn, job.get("id"), question) if isinstance(job, dict) and job.get("id") else None
        return answer_longform(question, job=job, kb=kb, llm=llm, research=research, prior=prior)
    return run
