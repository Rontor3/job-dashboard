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
        # Facts (spec 2026-10-11 + tournament 2026-10-16): when the bank has no answer, two readers over the fact
        # sheet — the local model (self.llm) and a Haiku plan (facts_llm, schema only) — fill only when they agree
        # (memory/factcards.py). Off unless facts_llm is given; without a local model the plan alone answers.
        self.facts_llm, self._skills, self._facts, self._snap = facts_llm, list(skills), None, None
        self._proposed: dict = {}           # ref -> a new fact Haiku proposed (MISSING), saved when you answer

    def _fact_sheet(self):
        """(facts, cards, plan cache), rebuilt when the bank changed — a fact told mid-run is used at once."""
        from . import facts as F
        from .factcards import Cards, PlanCache
        snap = self.conn.execute("SELECT count(*), max(updated_at) FROM qbank_entry").fetchone()
        if self._facts is None or snap != self._snap:
            self._facts = F.build(self.conn, self.contact, self._skills)
            self._cards, self._plans = Cards(self._facts, self.embed), PlanCache(self.conn, self._facts)
            self._snap = snap
        return self._facts, self._cards, self._plans

    def _from_facts(self, f):
        import json
        import re
        from ..orchestrator.sensitive import is_sensitive
        from . import factcards
        from .qbank_promote import save_fact
        if (self.facts_llm is None or f.kind in _NOT_FOR_PLANS or f.purpose == "attestation"
                or is_junk(f) or is_sensitive(f)):
            return None
        facts, cards, plans = self._fact_sheet()
        question = factcards.question_of(f.label, f.ref)
        value, note = factcards.answer(question, f.kind, f.options or [], self.job, facts, cards,
                                       local_llm=self.llm, haiku_llm=self.facts_llm, cache=plans,
                                       hint=f"{f.ref} {getattr(f, 'input_type', '') or ''}")
        if m := re.search(r"(MISSING|DERIVE) (\{.*\})", note):
            proposal = json.loads(m.group(2))
            if m.group(1) == "MISSING":
                self._proposed[f.ref] = {**proposal, "company": self.job.get("company")}
            elif value:                                   # a formula named once: every later wording reuses it
                save_fact(self.conn, proposal["key"], proposal.get("type"), proposal.get("desc") or question,
                          wording=question, embed=self.embed, plan=proposal["plan"])
        return (Match(LIKELY, kind="plan", note=f"from your facts: {note}"), value) if value else None

    def missing_for(self, f):
        """The fact Haiku said this field needs ({key, type, ask, company}), or None."""
        return self._proposed.get(f.ref)

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
