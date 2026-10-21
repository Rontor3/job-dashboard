"""What your insights taught: one row per accepted insight, kept forever (superseded, never deleted).

An insight is filed where it removes the cause (orchestrator/insight.py): a fact or a default goes to the question
bank, a different wording becomes a bank link — this table only logs those (`filed_in`, the value it replaced). What
no store can hold — how to read a kind of question, what material an essay should draw on — stays here as an active
RULE: "when a question is about <concept>, <rule>". A rule fires only on questions whose concept is close
(`for_question`), and `reach` shows which past questions it would have touched before you save it.

    lever      trust | fact | lookup | policy | derive | shape | identify | scope | guide
    applies_to question (same wording) | similar (same concept) | long (every essay) | short (every short field)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np

RULE_LEVERS = ("derive", "shape", "identify", "scope", "guide")    # the ones that live here as rules
SIM = 0.6          # ponytail: one fixed concept threshold; tune it from hits vs later edits per rule
SAME = 0.85        # a new rule this close to an active one on the same lever replaces it


def ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS answer_lesson (
        id INTEGER PRIMARY KEY AUTOINCREMENT, lever TEXT NOT NULL, applies_to TEXT NOT NULL,
        concept TEXT, qkey TEXT, rule TEXT, why TEXT, notes TEXT, source_row INTEGER,
        filed_in TEXT, before_json TEXT, vec BLOB,
        status TEXT NOT NULL DEFAULT 'active', hits INTEGER NOT NULL DEFAULT 0,
        created_at TEXT, updated_at TEXT)""")
    if "max_words" not in [r[1] for r in conn.execute("PRAGMA table_info(answer_lesson)")]:
        conn.execute("ALTER TABLE answer_lesson ADD COLUMN max_words INTEGER")     # a length the note set: a hard cap
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vec(embed, text):
    return np.asarray(embed([text])[0], dtype="float32") if text else None


def add(conn, d: dict, embed) -> int:
    """Log one accepted insight. A rule supersedes an active rule on the same lever and (nearly) the same concept."""
    ensure(conn)
    from job_dashboard.qa_store import norm_key
    lever = d["lever"]
    is_rule = lever in RULE_LEVERS
    v = _vec(embed, d.get("concept") or d.get("label")) if is_rule else None
    if is_rule and v is not None:
        for rid, blob in conn.execute("SELECT id, vec FROM answer_lesson WHERE status='active' AND lever=? "
                                      "AND vec IS NOT NULL", (lever,)).fetchall():
            if float(np.frombuffer(blob, dtype="float32") @ v) >= SAME:
                conn.execute("UPDATE answer_lesson SET status='superseded', updated_at=? WHERE id=?", (_now(), rid))
    now = _now()
    cur = conn.execute(
        "INSERT INTO answer_lesson (lever, applies_to, concept, qkey, rule, why, notes, source_row, filed_in, "
        "before_json, vec, status, created_at, updated_at, max_words) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (lever, d.get("applies_to") or "question", d.get("concept"), norm_key(d.get("label") or ""), d.get("rule"),
         d.get("why"), json.dumps(d.get("notes") or []), d.get("source_row"), d.get("filed_in"),
         json.dumps(d["before"]) if "before" in d else None, None if v is None else v.tobytes(),
         "active" if is_rule else "filed", now, now, d.get("max_words")))
    conn.commit()
    return cur.lastrowid


def _rows(conn, where="1=1", args=()):
    ensure(conn)
    cur = conn.execute(f"SELECT id, lever, applies_to, concept, qkey, rule, why, notes, source_row, filed_in, "
                       f"before_json, status, hits, created_at, updated_at, max_words FROM answer_lesson WHERE {where} "
                       f"ORDER BY id DESC", args)
    cols = [c[0] for c in cur.description]
    out = []
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        d["notes"] = json.loads(d["notes"] or "[]")
        d["before"] = json.loads(d.pop("before_json")) if d.get("before_json") else None
        out.append(d)
    return out


def listing(conn) -> list[dict]:
    return _rows(conn)


def update(conn, lesson_id: int, **fields) -> bool:
    allowed = {k: v for k, v in fields.items() if k in ("rule", "applies_to", "status", "concept") and v is not None}
    if not allowed:
        return False
    if allowed.get("status") not in (None, "active", "off"):
        raise ValueError("status must be active or off")
    if allowed.get("applies_to") not in (None, "question", "similar", "long", "short"):
        raise ValueError("applies_to must be question, similar, long or short")
    sets = ", ".join(f"{k}=?" for k in allowed)
    cur = conn.execute(f"UPDATE answer_lesson SET {sets}, updated_at=? WHERE id=?", (*allowed.values(), _now(), lesson_id))
    conn.commit()
    return cur.rowcount == 1


def is_long(kind: str) -> bool:
    return kind == "textarea"


def _matches(rule: dict, qkey: str, long_q: bool, sim: float | None) -> bool:
    scope = rule["applies_to"]
    if scope == "question":
        return rule["qkey"] == qkey
    if scope == "long":
        return long_q
    if scope == "short":
        return not long_q
    return rule["qkey"] == qkey or (sim is not None and sim >= SIM)


def for_question(conn, question: str, kind: str, embed, *, levers=RULE_LEVERS, count=True) -> list[dict]:
    """Active rules that apply to this question (same wording, same concept, or its kind class)."""
    ensure(conn)
    from job_dashboard.qa_store import norm_key
    marks = ",".join("?" * len(levers))
    rows = conn.execute(f"SELECT id, lever, applies_to, concept, qkey, rule, vec, max_words FROM answer_lesson "
                        f"WHERE status='active' AND lever IN ({marks})", tuple(levers)).fetchall()
    if not rows:
        return []
    qkey, long_q = norm_key(question), is_long(kind)
    qv = _vec(embed, question) if any(r[2] == "similar" for r in rows) else None
    hit = []
    for rid, lever, scope, concept, rk, rule, blob, words in rows:
        sim = float(np.frombuffer(blob, dtype="float32") @ qv) if (blob and qv is not None) else None
        r = {"id": rid, "lever": lever, "applies_to": scope, "concept": concept, "qkey": rk, "rule": rule,
             "max_words": words}
        if _matches(r, qkey, long_q, sim):
            hit.append(r)
    if hit and count:
        conn.executemany("UPDATE answer_lesson SET hits = hits + 1 WHERE id=?", [(r["id"],) for r in hit])
        conn.commit()
    return hit


def steer(rules: list[dict]) -> dict:
    """{'scope': 'general'|None, 'rule': text, 'max_words': n|None} for an answer engine; empty when no rule applies."""
    if not rules:
        return {}
    scope = next((r["rule"] for r in rules if r["lever"] == "scope"), None)
    text = "\n".join(f"- {r['rule']}" for r in rules if r.get("rule"))
    caps = [r["max_words"] for r in rules if r.get("max_words")]
    return {"scope": "general" if scope else None, "rule": text, "ids": [r["id"] for r in rules],
            "max_words": min(caps) if caps else None}


def reach(conn, concept: str, applies_to: str, label: str, kind: str, embed, limit: int = 12) -> dict:
    """Which distinct past questions (application_qa) a rule with this concept/scope would have applied to."""
    from job_dashboard.qa_store import norm_key
    rows = conn.execute("SELECT qkey, MIN(label), kind, COUNT(*) FROM application_qa WHERE qkey IS NOT NULL "
                        "AND qkey != '' GROUP BY qkey").fetchall()
    probe = {"applies_to": applies_to, "qkey": norm_key(label)}
    sims = [None] * len(rows)
    if applies_to == "similar" and concept and rows:
        vecs = np.asarray(embed([r[1] for r in rows]), dtype="float32")
        sims = list(vecs @ _vec(embed, concept))
    hits = [(r[1], r[3], s) for r, s in zip(rows, sims)
            if _matches(probe, r[0], is_long(r[2] or ""), None if s is None else float(s))]
    hits.sort(key=lambda h: -(h[2] or 0))
    return {"count": len(hits), "rows": sum(h[1] for h in hits),
            "examples": [{"label": h[0], "seen": h[1]} for h in hits[:limit]]}


def file(conn, p: dict, answer, embed) -> dict:
    """File an accepted insight where it removes the cause; returns {lesson_id, filed_in}.
    p = rewrite()'s proposal (lever, label, kind, entry_id, value, concept, rule, why, applies_to, derived, …)."""
    from . import qbank
    from .qbank_promote import save_fact
    lever, label, kind = p["lever"], p["label"], p.get("kind") or "text"
    if str(p.get("entry_id") or "").startswith("profile:"):    # a profile value: one saved question reads that column
        col = p["entry_id"].split(":", 1)[1]
        eid = next((e["id"] for e in qbank.entries(conn) if e.get("profile_ref") == col), None)
        if eid is None:
            eid = qbank.new_entry_id(conn, col)
            qbank.upsert_entry(conn, {"id": eid, "question": col.replace("_", " "), "topic": "profile",
                                      "atype": "text", "profile_ref": col})
        p = {**p, "entry_id": eid}
    entry = qbank.get_entry(conn, p["entry_id"]) if p.get("entry_id") else None
    rec = {k: p.get(k) for k in ("lever", "applies_to", "concept", "rule", "why", "notes", "source_row", "label",
                                 "max_words")}
    if lever in ("trust", "lookup") or (lever == "identify" and entry):
        if entry:
            qbank.add_wording(conn, label, entry["id"], embed([label])[0], "human", replace=True)
            rec["filed_in"] = f"wording -> {entry['id']}"
        else:                                             # right, but no saved answer holds it yet: now one does
            eid = qbank.add_entry(conn, question=label, kind=kind, answer=str(answer), embed=embed)
            rec["filed_in"] = f"new answer {eid}"
        if lever != "identify":
            return {"lesson_id": add(conn, rec, embed), "filed_in": rec["filed_in"]}
    if lever in ("fact", "policy"):
        value = str(p.get("value") or answer)
        if entry and entry.get("profile_ref"):
            from job_dashboard.apply.store import get_application_profile
            from job_dashboard.profile_intel import _set_profile
            rec["before"] = {"profile": entry["profile_ref"],
                             "value": (get_application_profile(conn) or {}).get(entry["profile_ref"])}
            _set_profile(conn, entry["profile_ref"], value)
            rec["filed_in"] = f"profile {entry['profile_ref']}"
        elif entry:
            rec["before"] = {"entry": entry["id"], "answer": entry.get("answer")}       # the old value stays here
            qbank.set_answer(conn, entry["id"], value)
            rec["filed_in"] = f"answer {entry['id']}"
        else:
            eid = qbank.add_entry(conn, question=p.get("concept") or label, kind=kind, answer=value, embed=embed,
                                  topic="policy" if lever == "policy" else "misc")
            rec["filed_in"] = f"new answer {eid}"
            entry = qbank.get_entry(conn, eid)
        qbank.add_wording(conn, label, entry["id"], embed([label])[0], "human", replace=True)
        return {"lesson_id": add(conn, rec, embed), "filed_in": rec["filed_in"]}
    derived = p.get("derived")
    if lever == "derive" and isinstance(derived, dict) and derived.get("key") and derived.get("plan"):
        key = save_fact(conn, derived["key"], derived.get("type"), derived.get("desc") or p.get("concept") or label,
                        wording=label, embed=embed, plan=derived["plan"])
        rec["filed_in"] = f"derived fact {key}"
        return {"lesson_id": add(conn, {**rec, "lever": "fact"}, embed), "filed_in": rec["filed_in"]}
    rec["filed_in"] = rec.get("filed_in") or "rule"
    return {"lesson_id": add(conn, rec, embed), "filed_in": rec["filed_in"]}
