"""plan -> retrieve -> write -> verify. Same return shape as draft_screening_answer (plus how the answer was built),
so judgment.py can use either. Never raises."""
from __future__ import annotations

import json
import os
import re

from job_dashboard import qa_store
from job_dashboard.apply.screening import _facts_block, _general_answer
from job_dashboard.letter.grounding import check_grounding

from .kb import KnowledgeBase
from .limits import field_limit
from .needs import plan_needs
from .recipes import retrieve
from .verify import fit_length, invented_projects, leak_check
from .write import draft


def _company_text(research) -> str:
    block = _facts_block(research)
    return "" if block.strip() == "(none)" else block


def answer_longform(question, *, job, kb, llm, research=None, limit=None, prior=None) -> dict:
    jd = (job.get("description") if isinstance(job, dict) else "") or ""
    plan = plan_needs(question, jd, kb, llm, prior)
    chunks = retrieve(plan, kb, question=question, jd_text=jd, company_text=_company_text(research))
    flags: list[str] = []

    hyp = "approach" in plan.needs
    out = draft(question, chunks, job, llm, limit, hypothetical=hyp)
    answer = out["answer"]
    if answer is not None:
        leaks = leak_check(answer, chunks, kb)
        if leaks:                                    # one redraft, naming what to leave out
            names = tuple(kb.units[p]["title"] for p in leaks)
            retry = draft(question, chunks, job, llm, limit, avoid=names, hypothetical=hyp)
            if retry["answer"]:
                out, answer = retry, retry["answer"]
                leaks = leak_check(answer, chunks, kb)
            if leaks:
                flags.append("project_leak:" + ",".join(leaks))
    if answer is not None:
        fake = invented_projects(answer, chunks)
        if fake:                                         # a project name that is in none of the material: never fill it
            flags.append("invented_project:" + ",".join(fake))
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
    # A draft that still names another project must not be filled: confidence=None makes judge()'s min_conf
    # gate hold the field as needs-answer for the human instead.
    # A draft that says the candidate has NOT done the thing is the model running out of material, not a fact about
    # the candidate: never fill it, hold it for the human the same way.
    if re.match(r"\s*(i\s+(have\s+not|haven'?t|do\s+not|don'?t|did\s+not|didn'?t)|no,)\b", answer, re.I):
        flags.append("denies_experience")
    confidence = None if any(f.startswith(("project_leak", "denies_experience", "invented_project")) for f in flags) else out["confidence"]
    return {"answer": answer, "flags": flags, "unsupported_company_claims": unsupported,
            "confidence": confidence, "basis": out["basis"], "prompt": out["prompt"],
            "needs": list(plan.needs), "project_id": plan.project_id, "used": [c.id for c in chunks],
            "plan_source": plan.source, "plan_reason": plan.reason, "chunks": chunks}


def prior_project(conn, job_id, label) -> str | None:
    """The project of this job's earlier draft of this question, but only one the user kept (accepted in the tracker).
    The pipeline's own earlier pick does not stick: a re-run must get the benefit of a better ranking."""
    try:
        row = conn.execute("SELECT context_json FROM application_qa WHERE job_id=? AND qkey IN (?, ?) "
                           "AND outcome = 'kept' AND json_extract(context_json, '$.project_id') IS NOT NULL ORDER BY id DESC LIMIT 1",
                           (job_id, qa_store.norm_key(label), qa_store.norm_key(label.rstrip(" *")))).fetchone()   # norm_key keeps a required-marker "*"
        return (json.loads(row[0]) if row and row[0] else {}).get("project_id")
    except Exception:
        return None


def make_longform(conn, job, contact, llm, research, ingredients_path, job_id=None):
    """The callable judgment.py uses: run(question, field) -> result dict. The knowledge base is loaded once."""
    from career_agent.memory.qbank import default_embed       # the on-device MiniLM the question bank already uses
    kb = KnowledgeBase.load(conn, ingredients_path, contact, embed=default_embed)
    found: dict = {}

    def research_of(j):
        """Company research, looked up once per company and only when an answer needs it (longform/research.py)."""
        def get():
            key = (j or {}).get("company") or ""
            if key not in found:
                from .research import research_for
                found[key] = research if getattr(research, "facts", None) else research_for(conn, j)
            return found[key]
        return get

    def lessons_for(question):
        """The applicant's essay lessons that apply to this question (memory/lessons.py); {} when none."""
        try:
            from career_agent.memory import lessons
            return lessons.steer(lessons.for_question(conn, question, "textarea", default_embed, levers=("scope", "guide")))
        except Exception as e:                           # a broken lesson store never blocks an answer
            print(f"[warn] lessons unavailable: {e!r}", flush=True)
            return {}

    def run(question, field=None, current_job=None, steer=None):
        j = current_job if isinstance(current_job, dict) and current_job else job   # apply.py may swap the job later
        jid = job_id if job_id is not None else (job.get("id") if isinstance(job, dict) else None)
        steer = lessons_for(question) if steer is None else steer
        if os.getenv("CAREER_AGENT_LONGFORM_LOGIC", "asks") == "asks":
            # ask by ask (longform/asks.py): held-out 1.00 answer relevancy / 0.95 faithfulness vs this module's
            # answer_longform 1.00 / 0.56 (scripts/longform_iterate.py, Haiku judge, 2026-10-12)
            from .asks import answer_asks
            from .corpus import Corpus
            res = answer_asks(question, job=j, kb=kb, corpus=Corpus(kb, j), llm=llm, limit=field_limit(field),
                              research=research_of(j), steer=steer)
            return {**res, **({"lessons": steer["ids"]} if steer.get("ids") else {})}
        prior = prior_project(conn, jid, question) if jid else None
        return answer_longform(question, job=j, kb=kb, llm=llm, research=research, prior=prior, limit=field_limit(field))
    run.kb = kb
    return run


def make_longform_or_none(conn, job, contact, llm, research, ingredients_path, job_id=None):
    """make_longform, or None (with a warning) when it cannot be built — the old drafter then answers."""
    try:
        return make_longform(conn, job, contact, llm, research, ingredients_path, job_id=job_id)
    except Exception as e:
        print(f"[warn] longform unavailable ({type(e).__name__}: {e}); using the standard drafter", flush=True)
        return None
