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


def promote_answer(conn, field, answer, embed) -> str | None:
    """Add/fill the bank entry for this question; the entry id, or None when
    it stays with the application."""
    text = str(answer or "").strip()
    label = (getattr(field, "label", "") or "").strip()
    if not text or not label or getattr(field, "kind", "") == "file" or _COMPANY_SPECIFIC.search(label):
        return None
    question = split_escape(label)[0] or label
    eid = qbank.exact(conn, question)
    if eid is None:
        return qbank.add_entry(conn, question=question, kind=field.kind, answer=text, embed=embed)
    entry = qbank.get_entry(conn, eid)
    if entry and not (entry.get("answer") or "").strip():
        qbank.set_answer(conn, eid, text)
        return eid
    return None
