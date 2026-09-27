"""The question bank behind the interface the fill loop already calls
(recall / record / record_corrections — same as the superseded AnswerMemory),
plus explain() for the QA recorder's retrieval trace.

The bank grows only from choices made on the dashboard (spec §3), so record()
and record_corrections() are deliberately no-ops: run-time answers are kept
per application in application_qa, and read-back edits are logged as
outcome='edited' by the recorder."""
from __future__ import annotations

from ..orchestrator.mapper import FillDecision, _action_for_kind
from . import qbank
from .qbank_match import CONFIDENT, DEFAULT_HIGH, NONE, answer_field


class QBankMemory:
    def __init__(self, conn, *, embed=None, llm=None, job=None, contact=None, high=DEFAULT_HIGH):
        self.conn, self.llm, self.high = conn, llm, high
        self.embed = embed or qbank.default_embed
        self.job, self.contact = job or {}, contact or {}
        qbank.seed_if_empty(conn, self.embed)
        self._cache: dict = {}

    def _answer(self, f):
        # trace_all() runs before recall() on the same fields: compute once
        # (the LLM pick is the expensive part).
        key = (f.ref, f.label, f.description, tuple(f.options or ()))
        if key not in self._cache:
            self._cache[key] = answer_field(self.conn, f, embed=self.embed, llm=self.llm,
                                            job=self.job, contact=self.contact, high=self.high)
        return self._cache[key]

    def explain(self, f) -> dict:
        m, _ = self._answer(f)
        accepted = m.entry_id if m.band != NONE else None
        basis = m.band + (f": {m.note}" if m.note else "") + (f"; escape {m.escape!r}" if m.escape else "")
        return {"retrieval_kind": m.kind, "retrieved_qkey": m.entry_id,
                "retrieval_score": round(m.score, 3),
                "candidates_json": [{"tier": "qbank", "qkey": e, "score": s, "accepted": e == accepted}
                                    for e, s in m.candidates],
                "confidence": int(round(m.score * 100)) if m.entry_id else None,
                "basis": basis}

    def recall(self, fields):
        """(decisions, still_need). Confident -> source 'qbank'; likely ->
        'qbank_likely' (filled, and recorded for review before submit)."""
        decisions, still = [], []
        for f in fields:
            m, value = self._answer(f)
            if m.band == NONE or value is None:
                still.append(f)
                continue
            decisions.append(FillDecision(f.ref, f.kind, f.label, value, _action_for_kind(f.kind),
                                          "qbank" if m.band == CONFIDENT else "qbank_likely"))
        return decisions, still

    def record(self, field, answer):
        return None

    def record_corrections(self, form, decisions, final_values):
        return None
