"""The insight backlog: open and unsure answers across every application, grouped by what they ask, biggest group
first — so one note fixes a whole class (16 'Acknowledge' boxes, every 'years of X' question) instead of one form.

Grouping is local (MiniLM, the bank's embedder): greedy, by the group's first question. Junk labels group by their
raw text too, which is what a field-meaning (identify) note needs.
"""
from __future__ import annotations

import numpy as np

from .qbank_match import qualifier_clash

GROUP = 0.88        # ponytail: one fixed similarity (same field type only); live 0.75 merged current with expected CTC


def open_rows(conn) -> list[dict]:
    """The newest open or unsure row per question wording, with how many rows (all jobs) share that wording."""
    cur = conn.execute(
        """SELECT a.id, a.label, a.kind, a.qkey, a.answer, a.source,
                  (SELECT COUNT(*) FROM application_qa b WHERE b.qkey = a.qkey
                   AND (b.status = 'needs_answer')) AS n
           FROM application_qa a
           WHERE a.status = 'needs_answer' AND a.qkey IS NOT NULL
             AND a.id = (SELECT MAX(id) FROM application_qa c WHERE c.qkey = a.qkey AND c.status = 'needs_answer')""")
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def groups(conn, embed, limit: int = 12) -> list[dict]:
    rows = open_rows(conn)
    if not rows:
        return []
    vecs = np.asarray(embed([r["label"] or r["qkey"] for r in rows]), dtype="float32")
    order = sorted(range(len(rows)), key=lambda i: -rows[i]["n"])
    taken, out = set(), []
    for i in order:
        if i in taken:
            continue
        members = [j for j in order if j not in taken and rows[j]["kind"] == rows[i]["kind"]
                   and float(vecs[i] @ vecs[j]) >= GROUP
                   and not qualifier_clash(rows[i]["label"] or "", rows[j]["label"] or "")]   # current vs expected
        taken.update(members)
        ms = [rows[j] for j in members]
        out.append({"row_id": rows[i]["id"], "label": rows[i]["label"], "kind": rows[i]["kind"],
                    "answer": rows[i]["answer"], "source": rows[i]["source"],
                    "rows": sum(m["n"] for m in ms), "wordings": len(ms),
                    "examples": [m["label"] for m in ms[:6]]})
    out.sort(key=lambda g: -g["rows"])
    return out[:limit]
