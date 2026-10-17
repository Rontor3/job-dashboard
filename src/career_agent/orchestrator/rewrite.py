"""Rewrite one recorded answer from the applicant's insight, and say what accepting it would teach. Writes nothing:
the dashboard saves the answer (PUT /api/application-qa/{id}/answer) and the lesson (POST /api/lessons) on Accept.

    rewrite(conn, row_id, notes, engines) -> {answer, directive, proposal, trace}

Each lever runs through the engine that already answers that kind of field — the question bank (trust, fact,
lookup, policy, identify), the fact plans (derive, shape, short guide), the essay writer (scope, long guide) — so a
rewrite here is exactly what the next run would produce once the lesson is filed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from job_dashboard import qa_store

from ..memory import lessons, qbank
from ..memory.qbank_match import CONFIDENT, fit_option, match_question, resolve_value
from .insight import checkbox_default, interpret

ORIGIN_WORDS = {"saved_exact": "your saved answer (exact wording)", "saved": "your saved answers",
                "similar": "a similar saved question (a best guess)", "model": "written by the model",
                "profile": "your profile / standard rules", "board": "prefilled by the job board",
                "you": "typed by you", "open": "left blank — no answer found"}


@dataclass
class Engines:
    llm: Callable                                   # local model first, Claude fallback (claude_assist)
    embed: Callable                                 # local MiniLM (qbank.default_embed)
    facts_llm: Optional[Callable] = None            # Haiku plan writer (schema only); None -> no plan levers
    longform: Optional[Callable] = None             # (question, steer) -> {answer, ...}; None -> no essay rewrite
    trace: list = field(default_factory=list)


def _job(conn, job_id) -> dict:
    row = conn.execute("SELECT title, company, location, description FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(zip(("title", "company", "location", "description"), row)) if row else {}


def _contact(conn) -> dict:
    from job_dashboard.apply.store import get_application_profile
    return get_application_profile(conn) or {}


def load_row(conn, row_id: int) -> dict | None:
    cur = conn.execute("SELECT * FROM application_qa WHERE id=?", (row_id,))
    r = cur.fetchone()
    return qa_store._row(cur, r) if r else None


def _norm(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip().lower()


def _entry_holding(conn, value, question, job, contact, embed):
    """The bank entry whose current value IS this answer (closest to the question if several), or None."""
    want, best = _norm(value), (None, -2.0)
    if not want:
        return None
    qv = embed([question])[0]
    for e in qbank.entries(conn):
        if e.get("topic") == "story":
            continue
        try:
            got = resolve_value(conn, e, question=e["question"], escape=None, job=job, contact=contact)
        except Exception:
            continue
        if _norm(got) == want:
            score = float(embed([e["question"]])[0] @ qv)
            if score > best[1]:
                best = (e["id"], score)
    if best[0] is None:                                   # held in your profile, no saved question reads it yet
        col = next((k for k, v in (contact or {}).items() if k != "updated_at" and _norm(v) == want), None)
        return f"profile:{col}" if col else None
    return best[0]


def _from_bank(conn, query, row, job, contact, eng):
    """(answer, entry id) for the first query the bank matches, fitted to the field's options."""
    for q in [x for x in query if x]:
        m = match_question(conn, q, embed=eng.embed, llm=eng.llm)
        eng.trace.append(f"bank lookup {q[:60]!r} -> {m.entry_id} ({m.band}, {round(m.score, 2)})")
        if not m.entry_id:
            continue
        entry = qbank.get_entry(conn, m.entry_id)
        value = resolve_value(conn, entry, question=row["label"], escape=None, job=job, contact=contact,
                              options=row.get("options_json") or ())
        if value:
            return fit_option(row["label"], value, row.get("options_json") or [], entry.get("synonyms"), eng.llm), m.entry_id
    return None, None


def _from_plan(conn, row, job, contact, guidance, eng):
    """(answer, note) from the fact plans with the insight as the field's instruction."""
    if eng.facts_llm is None:
        return None, "fact plans are off (no plan model)"
    from ..memory import facts as F
    from ..memory import factcards
    facts = {**F.build(conn, contact), **F.job_facts(job)}
    cards = factcards.Cards(facts, eng.embed)
    question = factcards.question_of(row["label"], row.get("ref") or "")
    value, note = factcards.answer(question, row.get("kind") or "text", row.get("options_json") or [], job, facts,
                                   cards, local_llm=eng.llm, haiku_llm=eng.facts_llm, cache=None,
                                   hint=row.get("ref") or "", guidance=guidance)
    eng.trace.append(f"fact plan: {note[:160]}")
    return value, note


def rewrite(conn, row_id: int, notes: list[str], eng: Engines) -> dict:
    row = load_row(conn, row_id)
    if row is None:
        raise KeyError(row_id)
    job, contact = _job(conn, row["job_id"]), _contact(conn)
    options = row.get("options_json") or []
    d = interpret({"label": row["label"], "kind": row.get("kind"), "options": options,
                   "origin": ORIGIN_WORDS.get(qa_store.origin(row), "unknown")}, notes, job, eng.llm)
    d = checkbox_default(d, row.get("kind") or "")
    lever, label = d["lever"], row["label"]
    proposal = {**d, "label": label, "source_row": row_id, "notes": notes, "kind": row.get("kind")}
    answer = None

    if lever == "trust":
        answer = row.get("answer")
        proposal["entry_id"] = _entry_holding(conn, answer, label, job, contact, eng.embed)
    elif lever in ("fact", "policy"):
        answer = fit_option(label, d["value"], options, None, eng.llm) or d["value"]
        m = match_question(conn, d.get("concept") or label, embed=eng.embed, llm=eng.llm)
        proposal["entry_id"] = m.entry_id if m.band == CONFIDENT else None     # a guess must never overwrite a fact
        eng.trace.append(f"{lever}: '{d['value']}' -> nearest saved question {m.entry_id} ({round(m.score, 2)})")
    elif lever in ("lookup", "identify"):
        asked = d.get("meaning") if lever == "identify" else d.get("query")
        answer, proposal["entry_id"] = _from_bank(conn, [asked, d.get("concept"), label], row, job, contact, eng)
        if answer is None and lever == "identify" and asked:                 # named, but not stored: work it out
            answer, _ = _from_plan(conn, {**row, "label": asked}, job, contact, d.get("rule"), eng)
    elif lever in ("derive", "shape") or (lever == "guide" and not lessons.is_long(row.get("kind") or "")):
        answer, note = _from_plan(conn, row, job, contact, d.get("rule") or notes[-1], eng)
        if m := re.search(r"DERIVE (\{.*\})", note or ""):
            proposal["derived"] = json.loads(m.group(1))
    else:                                                 # scope / guide on an essay
        if eng.longform is None:
            eng.trace.append("essay writer unavailable")
        else:
            steer = {"scope": "general" if lever == "scope" else None, "rule": f"- {d.get('rule') or notes[-1]}"}
            res = eng.longform(label, steer) or {}
            answer = res.get("answer")
            eng.trace.append(f"essay: {len(answer or '')} chars, flags {res.get('flags') or []}")

    if answer is not None and options and lever not in ("scope", "guide"):
        answer = fit_option(label, answer, options, None, eng.llm)
    return {"answer": answer, "directive": d, "proposal": proposal, "trace": eng.trace,
            "before": row.get("answer"), "origin": qa_store.origin(row)}
