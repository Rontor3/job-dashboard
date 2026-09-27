"""Per-application question/answer records and agent settings, in jobs.db.

One `application_qa` row per field per run (keyed by run_key + ref): what was
asked, what was filled and by which tier, the LLM's confidence/basis and the
exact context it was given, and — for retrieval analytics — what memory
retrieved. Written by career_agent during a run, read by the dashboard API.
Every writer here is best-effort at the call site: recording must never abort
an application run.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

DEFAULT_SETTINGS = {"answer_confidence_min": "60", "browser_min_interval_hours": "48", "browser_linkedin_enabled": "0",
                    "browser_naukri_enabled": "0", "browser_wellfound_enabled": "0",
                    "browser_instahyre_enabled": "0", "browser_iimjobs_enabled": "0",
                    "browser_indeed_enabled": "0", "browser_ycstartups_enabled": "0"}

_COLS = (
    "qkey", "label", "kind", "purpose", "answer", "source", "status",
    "confidence", "basis", "context_json", "unsupported_claims",
    "retrieval_kind", "retrieved_qkey", "retrieval_score", "candidates_json",
    "outcome",
)


def norm_key(label: str) -> str:
    """Same normalization as learned_answers.qkey, so the two join cleanly."""
    return re.sub(r"\s+", " ", (label or "").strip().lower()).strip(" ?:.")


def ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS application_qa (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER, run_key TEXT NOT NULL, ref TEXT NOT NULL,
        qkey TEXT, label TEXT, kind TEXT, purpose TEXT,
        answer TEXT, source TEXT, status TEXT,
        confidence INTEGER, basis TEXT, context_json TEXT, unsupported_claims TEXT,
        retrieval_kind TEXT, retrieved_qkey TEXT, retrieval_score REAL,
        candidates_json TEXT, outcome TEXT,
        created_at TEXT, updated_at TEXT,
        UNIQUE(run_key, ref))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aqa_job_status ON application_qa(job_id, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aqa_qkey ON application_qa(qkey)")
    conn.execute("CREATE TABLE IF NOT EXISTS agent_settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enc(v):
    return json.dumps(v) if isinstance(v, (list, dict)) else v


def record(conn, *, job_id, run_key: str, ref: str, label: str, **fields) -> None:
    """Insert or update the row for (run_key, ref); only the given fields change
    on update, so a later stage (e.g. human answered) doesn't wipe earlier data."""
    ensure(conn)
    fields["label"] = label
    fields["qkey"] = norm_key(label)
    unknown = set(fields) - set(_COLS)
    if unknown:
        raise ValueError(f"unknown application_qa fields: {sorted(unknown)}")
    now = _now()
    vals = {k: _enc(v) for k, v in fields.items()}
    cols = list(vals)
    conn.execute(
        f"INSERT INTO application_qa (job_id, run_key, ref, {', '.join(cols)}, created_at, updated_at) "
        f"VALUES (?, ?, ?, {', '.join('?' * len(cols))}, ?, ?) "
        f"ON CONFLICT(run_key, ref) DO UPDATE SET "
        f"{', '.join(f'{c}=excluded.{c}' for c in cols)}, updated_at=excluded.updated_at",
        [job_id, run_key, ref, *vals.values(), now, now],
    )
    conn.commit()


def _row(cur, r) -> dict:
    d = dict(zip([c[0] for c in cur.description], r))
    for k in ("context_json", "unsupported_claims", "candidates_json"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d


def open_questions(conn, job_id: int) -> list[dict]:
    """Questions still needing an answer for this job: the newest row per
    question, and only if that newest row is still `needs_answer` (a later run
    that filled it, or a reply, closes it)."""
    ensure(conn)
    cur = conn.execute(
        """SELECT * FROM application_qa a WHERE job_id = ? AND status = 'needs_answer'
           AND id = (SELECT MAX(id) FROM application_qa b
                     WHERE b.job_id = a.job_id AND b.qkey = a.qkey)
           ORDER BY id""", (job_id,))
    return [_row(cur, r) for r in cur.fetchall()]


def open_counts(conn) -> dict[int, int]:
    ensure(conn)
    rows = conn.execute(
        """SELECT job_id, COUNT(*) FROM application_qa a WHERE status = 'needs_answer'
           AND job_id IS NOT NULL
           AND id = (SELECT MAX(id) FROM application_qa b
                     WHERE b.job_id = a.job_id AND b.qkey = a.qkey)
           GROUP BY job_id""").fetchall()
    return {j: n for j, n in rows}


def mark_answered(conn, job_id: int, qkey: str, answer: str) -> int:
    """Close every open row for this job+question. Returns rows changed."""
    ensure(conn)
    cur = conn.execute(
        "UPDATE application_qa SET status='answered', answer=?, source='human', "
        "updated_at=? WHERE job_id=? AND qkey=? AND status='needs_answer'",
        (answer, _now(), job_id, qkey))
    conn.commit()
    return cur.rowcount


def asked_in_counts(conn) -> dict[str, int]:
    """qkey -> number of distinct jobs that asked it."""
    ensure(conn)
    return {k: n for k, n in conn.execute(
        "SELECT qkey, COUNT(DISTINCT job_id) FROM application_qa "
        "WHERE job_id IS NOT NULL GROUP BY qkey")}


def applications_for(conn, qkey: str) -> list[dict]:
    ensure(conn)
    cur = conn.execute(
        """SELECT j.id AS job_id, j.title, j.company, MAX(a.updated_at) AS last_asked
           FROM application_qa a JOIN jobs j ON j.id = a.job_id
           WHERE a.qkey = ? GROUP BY j.id ORDER BY last_asked DESC""", (qkey,))
    return [_row(cur, r) for r in cur.fetchall()]


def get_setting(conn, key: str) -> str:
    ensure(conn)
    r = conn.execute("SELECT value FROM agent_settings WHERE key=?", (key,)).fetchone()
    return r[0] if r else DEFAULT_SETTINGS[key]


def set_setting(conn, key: str, value) -> None:
    if key not in DEFAULT_SETTINGS:
        raise KeyError(key)
    ensure(conn)
    conn.execute("INSERT INTO agent_settings (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    conn.commit()


def confidence_min(conn) -> int:
    try:
        return max(0, min(100, int(get_setting(conn, "answer_confidence_min"))))
    except (TypeError, ValueError):
        return int(DEFAULT_SETTINGS["answer_confidence_min"])


# ── review + retrieval analytics ─────────────────────────────────────────────

_MEMORY = ("learned", "semantic")      # sources meaning "memory answered this"


def answers_used(conn, job_id: int) -> list[dict]:
    """What the agent filled for this job (newest row per question), so each
    can be reviewed: was the retrieved answer right?"""
    ensure(conn)
    cur = conn.execute(
        """SELECT * FROM application_qa a WHERE job_id = ? AND status IN ('filled', 'answered')
           AND id = (SELECT MAX(id) FROM application_qa b WHERE b.job_id = a.job_id AND b.qkey = a.qkey)
           ORDER BY id""", (job_id,))
    return [_row(cur, r) for r in cur.fetchall()]


def set_outcome(conn, row_id: int, outcome: str) -> bool:
    if outcome not in ("kept", "edited"):
        raise ValueError(outcome)
    ensure(conn)
    cur = conn.execute("UPDATE application_qa SET outcome=?, updated_at=? WHERE id=?",
                       (outcome, _now(), row_id))
    conn.commit()
    return cur.rowcount > 0


def retrieval_stats(conn) -> dict:
    """Every field of every run counts once (a re-run is another attempt).
    hit = retrieval found a usable entry; memory-answered = that entry actually
    filled the field (a semantic match below the autonomy bar is a hit that
    isn't used). wrong_rate is over reviewed memory-answered fields only."""
    ensure(conn)
    q = lambda sql, *a: conn.execute(sql, a).fetchall()
    total = q("SELECT COUNT(*) FROM application_qa")[0][0]
    mem_in = ",".join("?" * len(_MEMORY))
    hits = q("SELECT COUNT(*) FROM application_qa WHERE retrieval_kind IS NOT NULL AND retrieval_kind != 'none'")[0][0]
    by_tier = dict(q("SELECT retrieval_kind, COUNT(*) FROM application_qa WHERE retrieval_kind IS NOT NULL "
                     "AND retrieval_kind != 'none' GROUP BY retrieval_kind"))
    by_source = dict(q("SELECT CASE WHEN status='needs_answer' THEN 'unanswered' ELSE COALESCE(source,'unknown') END, "
                       "COUNT(*) FROM application_qa GROUP BY 1"))
    answered = q(f"SELECT COUNT(*) FROM application_qa WHERE source IN ({mem_in}) AND status != 'needs_answer'", *_MEMORY)[0][0]
    kept, edited = [q(f"SELECT COUNT(*) FROM application_qa WHERE source IN ({mem_in}) AND outcome=?", *_MEMORY, o)[0][0]
                    for o in ("kept", "edited")]
    wrong = q(f"""SELECT retrieved_qkey, SUM(outcome='edited'), SUM(outcome='kept') FROM application_qa
                  WHERE source IN ({mem_in}) AND outcome IS NOT NULL AND retrieved_qkey IS NOT NULL
                  GROUP BY retrieved_qkey HAVING SUM(outcome='edited') > 0
                  ORDER BY SUM(outcome='edited') DESC LIMIT 5""", *_MEMORY)

    def avg(outcome):
        r = q("SELECT AVG(confidence), COUNT(*) FROM application_qa WHERE source='judgment' "
              "AND confidence IS NOT NULL AND outcome=?", outcome)[0]
        return {"avg_confidence": round(r[0], 1) if r[0] is not None else None, "count": r[1]}

    gen = q("SELECT status, COUNT(*) FROM application_qa WHERE source='judgment' GROUP BY status")
    return {
        "total_fields": total,
        "retrieval_hits": hits, "hit_rate": round(hits / total, 3) if total else None,
        "by_tier": by_tier, "by_source": by_source,
        "answered_by_memory": answered,
        "retrieved_not_used": max(hits - answered, 0),
        "reviewed": {"kept": kept, "edited": edited,
                     "wrong_rate": round(edited / (kept + edited), 3) if kept + edited else None},
        "top_wrong_entries": [{"qkey": k, "edited": e, "kept": kp or 0} for k, e, kp in wrong],
        "generation": {"by_status": dict(gen), "kept": avg("kept"), "edited": avg("edited")},
    }


def recent_retrievals(conn, limit: int = 50) -> list[dict]:
    ensure(conn)
    cur = conn.execute(
        """SELECT a.id, a.job_id, j.title, j.company, a.label, a.answer, a.source, a.status, a.confidence,
                  a.retrieval_kind, a.retrieved_qkey, a.retrieval_score, a.candidates_json, a.outcome, a.created_at
           FROM application_qa a LEFT JOIN jobs j ON j.id = a.job_id
           ORDER BY a.id DESC LIMIT ?""", (max(1, min(limit, 200)),))
    return [_row(cur, r) for r in cur.fetchall()]
