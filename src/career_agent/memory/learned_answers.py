"""Learning loop: remember answers the human typed on past forms and reuse
them before escalating again. Short answers only (notice period, salary, years,
standard Qs) — textarea essays are per-job and never stored. Pure sqlite3 +
FTS5, no vectors, no new dependency.

Recall order per field: exact purpose match -> exact normalized-label match ->
FTS5 fuzzy on label, accepted only if token overlap >= _MIN_OVERLAP (a wrong
reuse is worse than one more escalation)."""
from __future__ import annotations

import re

from ..orchestrator.mapper import FillDecision, _action_for_kind

_MIN_OVERLAP = 0.5
_STOP = {"a", "an", "the", "of", "in", "to", "is", "are", "do", "you", "your",
         "have", "what", "how", "many", "at", "for", "and", "or", "please"}


def _norm(label: str) -> str:
    return re.sub(r"\s+", " ", (label or "").strip().lower()).strip(" ?:.")


def _tokens(label: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", (label or "").lower())
            if t not in _STOP and len(t) > 1}


def ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS learned_answers (
        qkey TEXT PRIMARY KEY, label TEXT, answer TEXT, purpose TEXT, updated_at TEXT)""")
    conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS learned_answers_fts
        USING fts5(label, qkey UNINDEXED)""")
    conn.commit()


class AnswerMemory:
    def __init__(self, conn):
        self.conn = conn
        ensure(conn)

    def record(self, field, answer) -> None:
        if field.kind == "textarea" or answer is None or str(answer).strip() == "":
            return                              # essays are per-job; skip blanks
        from datetime import datetime, timezone
        qkey = _norm(field.label)
        if not qkey:
            return
        self.conn.execute(
            "INSERT INTO learned_answers (qkey, label, answer, purpose, updated_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(qkey) DO UPDATE SET "
            "answer=excluded.answer, purpose=excluded.purpose, updated_at=excluded.updated_at",
            (qkey, field.label, str(answer), field.purpose,
             datetime.now(timezone.utc).isoformat()))
        self.conn.execute("DELETE FROM learned_answers_fts WHERE qkey=?", (qkey,))
        self.conn.execute("INSERT INTO learned_answers_fts (label, qkey) VALUES (?,?)",
                          (_norm(field.label), qkey))
        self.conn.commit()

    def _lookup(self, field):
        if field.kind == "textarea":
            return None
        # 1. same purpose -> reuse regardless of wording
        if field.purpose:
            row = self.conn.execute(
                "SELECT answer FROM learned_answers WHERE purpose=? ORDER BY updated_at DESC LIMIT 1",
                (field.purpose,)).fetchone()
            if row:
                return row[0]
        # 2. exact normalized label
        qkey = _norm(field.label)
        row = self.conn.execute(
            "SELECT answer FROM learned_answers WHERE qkey=?", (qkey,)).fetchone()
        if row:
            return row[0]
        # 3. FTS5 fuzzy, gated by token overlap
        toks = _tokens(field.label)
        if not toks:
            return None
        match = " OR ".join(sorted(toks))
        try:
            hits = self.conn.execute(
                "SELECT a.answer, a.label FROM learned_answers_fts f "
                "JOIN learned_answers a ON a.qkey=f.qkey "
                "WHERE learned_answers_fts MATCH ? ORDER BY bm25(learned_answers_fts) LIMIT 1",
                (match,)).fetchone()
        except Exception:
            return None
        if hits:
            cand = _tokens(hits[1])
            if cand and len(toks & cand) / len(toks | cand) >= _MIN_OVERLAP:
                return hits[0]
        return None

    def recall(self, fields):
        """(decisions, still_need) — fill fields we've seen answered, escalate the rest."""
        decisions, still = [], []
        for f in fields:
            ans = self._lookup(f)
            if ans is None:
                still.append(f)
            else:
                decisions.append(FillDecision(f.ref, f.kind, f.label, ans,
                                              _action_for_kind(f.kind), "learned"))
        return decisions, still
