"""One-off / maintenance operations on the question bank: pull usable rows out
of the superseded learned_answers table, and measure retrieval so FLOOR /
HIGH / MARGIN come from data instead of guesses (spec §2, §7)."""
from __future__ import annotations

from collections import Counter

import numpy as np

from . import qbank
from .qbank_match import CONFIDENT, is_junk, match_question, split_escape

# Out-of-bank questions: a good FLOOR sits above most of their best scores.
NEGATIVES = [
    "Why do you want to work at our company?",
    "Describe a time you failed and what you learned.",
    "What excites you about our mission?",
    "Have you used our product before? If yes, how?",
    "Tell us about a project you are proud of.",
    "What is your favourite programming language and why?",
    "Describe a disagreement with a teammate and how you resolved it.",
    "What would you build in your first 90 days?",
    "Anything else you would like us to know?",
    "Upload your cover letter",
    "What questions do you have for us?",
    "Describe your ideal manager.",
]


def migrate_learned(conn, embed) -> dict:
    """Move learned_answers rows into the bank. Only CONFIDENT matches migrate
    (no LLM here); an entry's existing answer/rule/profile_ref is never
    overwritten. Junk labels are reported and dropped."""
    from ..browser.form_model import Field
    from .learned_answers import ensure as ensure_learned
    ensure_learned(conn)
    report = {"migrated": [], "junk": [], "unmatched": []}
    for label, answer in conn.execute("SELECT label, answer FROM learned_answers ORDER BY rowid").fetchall():
        f = Field(ref="_migrate", kind="text", label=label or "", required=False)
        question = split_escape(label or "")[0]
        if is_junk(f) or not question:
            report["junk"].append(label)
            continue
        m = match_question(conn, question, embed=embed, llm=None)
        if m.band != CONFIDENT:
            report["unmatched"].append(label)
            continue
        e = qbank.get_entry(conn, m.entry_id)
        qbank.add_wording(conn, question, e["id"], embed([question])[0], "migrated")
        if e["answer"] is None and not e["rule"] and not e["profile_ref"]:
            qbank.set_answer(conn, e["id"], answer)
        report["migrated"].append(label)
    return report


def _pct(xs, p):
    return round(float(np.percentile(xs, p)), 3) if xs else None


def calibrate(conn, embed, negatives=NEGATIVES) -> dict:
    """Hold each wording out, search with it, record whether its own entry comes
    back on top. Suggested: FLOOR = p90 of out-of-bank best scores; HIGH = p95
    of wrong top-1 scores; MARGIN = p10 of the lead correct matches have."""
    rows = qbank.wordings(conn)
    if not rows:
        return {"evaluated": 0, "top1_accuracy": None, "suggested": {"FLOOR": None, "HIGH": None, "MARGIN": None}}
    per_entry = Counter(e for _, e, _ in rows)
    mat = np.stack([v for _, _, v in rows])
    right, wrong, gaps = [], [], []
    for i, (_, e, v) in enumerate(rows):
        if per_entry[e] < 2:
            continue                      # its entry has no other wording to find
        sims = mat @ v
        sims[i] = -2.0
        best: dict = {}
        for (_, e2, _), s in zip(rows, sims):
            best[e2] = max(best.get(e2, -2.0), float(s))
        top = sorted(best.items(), key=lambda kv: -kv[1])
        s2 = top[1][1] if len(top) > 1 else 0.0
        if top[0][0] == e:
            right.append(top[0][1])
            gaps.append(top[0][1] - s2)
        else:
            wrong.append(top[0][1])
    neg = [float((mat @ embed([t])[0]).max()) for t in negatives]
    n = len(right) + len(wrong)
    return {
        "evaluated": n,
        "top1_accuracy": round(len(right) / n, 3) if n else None,
        "right": {"p10": _pct(right, 10), "p50": _pct(right, 50)},
        "wrong": {"p50": _pct(wrong, 50), "p95": _pct(wrong, 95)},
        "negatives": {"p50": _pct(neg, 50), "p90": _pct(neg, 90)},
        "suggested": {"FLOOR": _pct(neg, 90), "HIGH": _pct(wrong, 95), "MARGIN": _pct(gaps, 10)},
    }


MERGES = [("relevant_experience_years", "total_experience_years"), ("interviewed_recently", "interviewed_before"),
          ("timeline_considerations", "earliest_start"), ("onsite_ok", "work_arrangement"),
          ("shifts_ok", "shift_pattern"), ("contract_ok", "employment_type"), ("full_time_ok", "employment_type")]
RETIRE = ["ctc_fixed_component", "ctc_variable_component", "other_offer_ctc", "whatsapp_ok", "sms_consent",
          "drug_test_ok", "driving_license", "passport_valid", "home_office_setup"]


def _active(conn, eid) -> bool:
    e = qbank.get_entry(conn, eid)
    return bool(e and e["status"] == "active")


def merge_entry(conn, src, dst) -> int:
    """Re-point src's wordings to dst and supersede src. Returns wordings moved; 0 if either side is missing
    or src is already superseded (idempotent). Nothing is deleted."""
    s, d = qbank.get_entry(conn, src), qbank.get_entry(conn, dst)
    if s is None or d is None or s["status"] != "active":
        return 0
    n = conn.execute("UPDATE qbank_wording SET entry_id=? WHERE entry_id=?", (dst, src)).rowcount
    qbank.set_status(conn, src, "superseded")
    return n


def cleanup(conn) -> dict:
    """Merge overlapping entries and retire rarely-asked ones (idempotent). Load the seed first so survivors exist."""
    merged = retired = 0
    for s, d in MERGES:
        if _active(conn, s) and qbank.get_entry(conn, d):
            merge_entry(conn, s, d)
            merged += 1
    for i in RETIRE:
        if _active(conn, i):
            qbank.set_status(conn, i, "superseded")
            retired += 1
    return {"merged": merged, "retired": retired}
