"""Explain what memory retrieval did for a field: which tier matched, which
entry, at what score, and what else was considered (including candidates the
gates rejected). Read-only: it replays AnswerMemory._lookup's ordering and the
semantic vault's gate rather than changing either, so retrieval behavior can't
be affected by tracing. tests/career_agent/test_retrieval_trace.py checks it
agrees with AnswerMemory.recall, so a change to the lookup order fails loudly.
"""
from __future__ import annotations

from . import learned_answers as _la
from .learned_answers import _MIN_OVERLAP, _norm, _tokens

# getattr: absent on older checkouts of learned_answers, where the purpose
# rule applies to every purpose — an empty set reproduces exactly that.
_WORDING_SENSITIVE_PURPOSES = getattr(_la, "_WORDING_SENSITIVE_PURPOSES", set())


def _learned(conn, f) -> tuple[str, str | None, float | None, list]:
    """(kind, matched_qkey, score, candidates) for the learned_answers tier."""
    if f.kind in ("textarea", "file") or f.purpose == "attestation":
        return "none", None, None, []
    if f.purpose and f.purpose not in _WORDING_SENSITIVE_PURPOSES:
        row = conn.execute("SELECT qkey FROM learned_answers WHERE purpose=? "
                           "ORDER BY updated_at DESC LIMIT 1", (f.purpose,)).fetchone()
        if row:
            return "purpose", row[0], 1.0, [{"tier": "learned", "qkey": row[0], "score": 1.0, "accepted": True}]
    qkey = _norm(f.label)
    if conn.execute("SELECT 1 FROM learned_answers WHERE qkey=?", (qkey,)).fetchone():
        return "label_exact", qkey, 1.0, [{"tier": "learned", "qkey": qkey, "score": 1.0, "accepted": True}]
    toks = _tokens(f.label)
    if not toks:
        return "none", None, None, []
    try:
        hits = conn.execute(
            "SELECT a.qkey, a.label FROM learned_answers_fts f JOIN learned_answers a ON a.qkey=f.qkey "
            "WHERE learned_answers_fts MATCH ? ORDER BY bm25(learned_answers_fts) LIMIT 3",
            (" OR ".join(sorted(toks)),)).fetchall()
    except Exception:
        return "none", None, None, []
    cands = []
    for i, (k, label) in enumerate(hits):
        cand = _tokens(label)
        overlap = len(toks & cand) / len(toks | cand) if cand else 0.0
        # _lookup only ever considers the top FTS hit
        cands.append({"tier": "learned", "qkey": k, "score": round(overlap, 3),
                      "accepted": i == 0 and overlap >= _MIN_OVERLAP})
    if cands and cands[0]["accepted"]:
        return "fts_fuzzy", cands[0]["qkey"], cands[0]["score"], cands
    return "none", None, None, cands


def explain(conn, vault, f) -> dict:
    """Retrieval fields for application_qa. Never raises."""
    try:
        kind, matched, score, cands = _learned(conn, f)
        if vault is not None and f.kind in ("text", "textarea"):
            sem = vault.candidates(f.label)
            for c in sem:
                cands.append({"tier": "semantic", "qkey": _norm(c["question"]), "score": round(c["distance"], 3),
                              "confidence": c["confidence"], "accepted": c["accepted"]})
            if kind == "none" and sem and sem[0]["accepted"]:
                kind, matched, score = "semantic", _norm(sem[0]["question"]), round(sem[0]["distance"], 3)
        return {"retrieval_kind": kind, "retrieved_qkey": matched,
                "retrieval_score": score, "candidates_json": cands}
    except Exception:
        return {"retrieval_kind": "none"}
