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
from .qbank_match import CONFIDENT, DEFAULT_HIGH, LIKELY, NONE, Match, answer_field, is_junk

_NOT_FOR_PLANS = ("file", "button", "textarea")     # uploads, clicks and essays are never a fact


class QBankMemory:
    def __init__(self, conn, *, embed=None, llm=None, job=None, contact=None, high=DEFAULT_HIGH,
                 facts_llm=None, skills=()):
        self.conn, self.llm, self.high = conn, llm, high
        self.embed = embed or qbank.default_embed
        self.job, self.contact = job or {}, contact or {}
        qbank.seed_if_empty(conn, self.embed)
        self._cache: dict = {}
        # Facts + plans (spec 2026-10-11): when the bank has no answer, a plan written by facts_llm from the fact
        # schema runs over the stored facts. Off unless a model is given. ponytail: plans cached per run only
        # (in memory), persist them in a plan table when this graduates from the live test.
        self.facts_llm, self._skills, self._facts, self._plans = facts_llm, list(skills), None, {}

    def _from_facts(self, f):
        from ..orchestrator.sensitive import is_sensitive
        from . import facts as F
        if (self.facts_llm is None or f.kind in _NOT_FOR_PLANS or f.purpose == "attestation"
                or is_junk(f) or is_sensitive(f)):
            return None
        if self._facts is None:
            self._facts = F.build(self.conn, self.contact, self._skills)
        value, note = F.answer(f.label, f.kind, f.options or [], self.job, self._facts, self.facts_llm,
                               cache=self._plans)
        return (Match(LIKELY, kind="plan", note=f"plan from your facts: {note}"), value) if value else None

    def _answer(self, f):
        # trace_all() runs before recall() on the same fields: compute once
        # (the LLM pick is the expensive part).
        key = (f.ref, f.label, f.description, tuple(f.options or ()))
        if key not in self._cache:
            try:
                self._cache[key] = answer_field(self.conn, f, embed=self.embed, llm=self.llm,
                                                job=self.job, contact=self.contact, high=self.high)
            except Exception as e:
                print(f"[warn] qbank lookup failed for {f.label!r}: {e}")
                self._cache[key] = (Match(band=NONE), None)
            m, value = self._cache[key]
            if m.band == NONE or value is None:
                try:
                    self._cache[key] = self._from_facts(f) or self._cache[key]
                except Exception as e:                  # CLI down, login expired: the bank's answer (none) stands
                    print(f"[warn] facts plan failed for {f.label!r}: {type(e).__name__}: {e}")
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
            source = "qbank" if m.band == CONFIDENT else "qbank_likely"
            if f.kind == "checkbox":
                # A tick box takes Yes -> tick, No -> make sure it is NOT ticked (sites pre-tick marketing opt-ins).
                # A REQUIRED box cannot be declined: leave it to the rule mapper (attestation), never untick it.
                yes = str(value).strip().lower() in ("yes", "true", "1", "y", "checked")
                if not yes and f.required:
                    still.append(f)
                    continue
                decisions.append(FillDecision(f.ref, f.kind, f.label, yes, "check" if yes else "uncheck", source))
                continue
            decisions.append(FillDecision(f.ref, f.kind, f.label, value, _action_for_kind(f.kind), source))
        return decisions, still

    def record(self, field, answer):
        return None

    def record_corrections(self, form, decisions, final_values):
        return None
