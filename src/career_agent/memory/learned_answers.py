"""The superseded learned_answers table (replaced by the question bank): its
schema, read by `qbank_admin.migrate_learned`, and the label normalization and
fuzzy-match gates that `retrieval_trace` replays."""
from __future__ import annotations

import re

_MIN_OVERLAP = 0.5
# Purposes where "same purpose" does NOT mean "same expected answer" — address
# questions vary wildly in what they actually want across ATSs (a real street
# address vs. a conditional placeholder like "type relocating if you'd need
# to relocate"), so they need an exact or fuzzy label match, never a purpose match.
_WORDING_SENSITIVE_PURPOSES = {"address"}
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
