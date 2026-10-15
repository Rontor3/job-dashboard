"""Human answers join the Answers tab (the question bank).

Whatever the human types in reply to a question during a run — on Telegram or
in the terminal — becomes (or fills) a bank entry, so the same question is
answered from the bank next time. Left with the application only: company-
specific essays ("why do you want to join us"), file uploads, blank replies.
An entry that already has an answer is never overwritten here (the dashboard's
Answers tab is where that is changed on purpose).
"""
from __future__ import annotations

import re

from . import qbank
from .qbank_match import split_escape

# Same family as the Telegram collector's company-question test: the answer
# is about THIS company, so it must not become a standing answer.
_COMPANY_SPECIFIC = re.compile(
    r"why\s+(this\s+)?(company|role|join|apply|us\b|our|do you want|are you interested)"
    r"|motivat|what.{0,20}attract|interest\s+in\s+(this|the|our)\s+(role|position|company|job)"
    r"|tell\s+us\s+why|what\s+interests\s+you|why\s+\w+\s+interest",
    re.I)


_ONE_APPLICATION = re.compile(r"\b(this|the)\s+(role|position|job|posting|opening|vacancy)\b"
                              r"|\b(indeed|naukri|linkedin|glassdoor|wellfound|instahyre|monster)\b", re.I)
_ATYPE = {"bool": "bool", "number": "number", "date": "date", "money": "text", "text": "text"}
NEAR = 0.85     # a proposed fact this close to an existing card IS that card (the wording is linked, no new card)


def save_fact(conn, key, ftype, desc, *, wording, embed, answer=None, plan=None) -> str:
    """A fact told once, under a reusable name: base (answer) or derived (plan, computed every run). The form's
    wording is linked to it so the same wording hits the bank directly next time."""
    exists = qbank.get_entry(conn, key)
    if not exists:
        qbank.upsert_entry(conn, {"id": key, "question": desc, "topic": "fact", "atype": _ATYPE.get(ftype, "text"),
                                  "rule": "derived" if plan else None, "slots": plan})
    if answer is not None and not (exists and (exists.get("answer") or "").strip()):
        qbank.set_answer(conn, key, answer)               # never overwrite what you told before
    qbank.add_wording(conn, wording, key, embed([wording])[0], "human" if answer is not None else "derived")
    conn.commit()
    return key


def _near_card(conn, ask, embed):
    """(entry id, score) of the closest existing bank fact to the proposed one's description, or (None, 0)."""
    rows = [(e["id"], e["question"]) for e in qbank.entries(conn)
            if e.get("topic") != "story" and not e.get("profile_ref")]     # a profile column is not a bank fact
    if not rows:
        return None, 0.0
    import numpy as np
    vecs = np.asarray(embed([ask] + [q for _, q in rows]))
    sims = vecs[1:] @ vecs[0]
    j = int(np.argmax(sims))
    return rows[j][0], float(sims[j])


def _promote_fact(conn, question, text, missing, embed) -> str | None:
    """Your reply to a question no fact covered: saved as the fact Haiku named — unless it is about this one
    application, or an existing card already is that fact (then the wording joins that card)."""
    company = (missing.get("company") or "").strip()
    ask = str(missing.get("ask") or question)
    if company:
        ask = re.sub(re.escape(company), "the employer", ask, flags=re.I)
    if _ONE_APPLICATION.search(f"{missing.get('key', '')} {ask}") or (company and company.lower() in question.lower()):
        return None                                       # how you found this job, this role: stays with it
    near, score = _near_card(conn, ask, embed)
    if near and score >= NEAR:
        return save_fact(conn, near, missing.get("type"), ask, wording=question, embed=embed, answer=text)
    key = str(missing.get("key") or "")
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", key):
        return None
    return save_fact(conn, key, missing.get("type"), ask, wording=question, embed=embed, answer=text)


def promote_answer(conn, field, answer, embed, missing=None) -> str | None:
    """Add/fill the bank entry for this question; the entry id, or None when
    it stays with the application. `missing` = the fact Haiku said this field needs: the reply is saved as that
    fact (one card for every wording), not as one more question."""
    text = str(answer or "").strip()
    label = (getattr(field, "label", "") or "").strip()
    if not text or not label or getattr(field, "kind", "") == "file" or _COMPANY_SPECIFIC.search(label):
        return None
    from ..orchestrator.sensitive import is_sensitive
    if is_sensitive(field):
        return None                                   # bank / ID details never enter the Answers
    question = split_escape(label)[0] or label
    if missing:
        return _promote_fact(conn, question, text, missing, embed)
    eid = qbank.exact(conn, question)
    if eid is None:
        return qbank.add_entry(conn, question=question, kind=field.kind, answer=text, embed=embed)
    entry = qbank.get_entry(conn, eid)
    if entry and not (entry.get("answer") or "").strip():
        qbank.set_answer(conn, eid, text)
        return eid
    return None
