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
import types
from datetime import datetime, timezone

DEFAULT_SETTINGS = {"mail_last_scan": "0",            # epoch of the last Gmail scan (mail_scan.py)
                    "profile_autofill_at": "",         # when the résumé was last read into the profile
                    "inbox_snoozed": "{}",             # Inbox items skipped: {key: ISO until}
                    "insight_local_only": "0",         # 1 = rewriting an answer never falls back to Claude
                    "telegram_wait_minutes": "10",     # apply queue: live Telegram questions, then park
                    "answer_confidence_min": "60", "qbank_confident_min": "87", "browser_min_interval_hours": "48", "browser_linkedin_enabled": "0",
                    "browser_naukri_enabled": "0", "browser_wellfound_enabled": "0",
                    "browser_instahyre_enabled": "0", "browser_iimjobs_enabled": "0",
                    "browser_indeed_enabled": "0", "browser_ycstartups_enabled": "0",
                    "gmail_confirmation_check": "0",    # look for the "application sent" EMAIL as proof (subjects only; off by default)
                    "autosubmit_daily_cap": "5",       # most automatic submits in any 24h (autonomy.autosubmit_policy)
                    # Apply queue: standing per-board authorization to auto-submit (0/1).
                    **{f"autosubmit_{b}": "0" for b in ("naukri", "linkedin", "indeed", "iimjobs", "instahyre",
                                                        "wellfound", "workatastartup", "career_site")},
                    # 1 = you waive the "first submit on this kind of site is yours" rule for that board (0 = keep it)
                    **{f"trust_first_{b}": "0" for b in ("naukri", "linkedin", "indeed", "iimjobs", "instahyre",
                                                         "wellfound", "workatastartup", "career_site")}}

_COLS = (
    "qkey", "label", "kind", "purpose", "answer", "source", "status",
    "confidence", "basis", "context_json", "unsupported_claims",
    "retrieval_kind", "retrieved_qkey", "retrieval_score", "candidates_json",
    "outcome", "page", "options_json", "policy_verdict",
)

# Job statuses whose lifecycle is over — the same settled set submit_watch's
# requeue treats as done. Deliberately NOT 'failed': a failed (or parked) job
# re-queues once its last open question is answered (qa_routes._requeue_if_unblocked
# reads open_questions for that), so those asks must stay live. And NOT
# 'dismissed': a dismissed job is merely out of the review feed and can return.
SETTLED_JOB_STATUSES = ("applied", "interviewing", "offer", "rejected", "closed")


def norm_key(label: str) -> str:
    """The question key: label lowercased, spaces collapsed, edge ' ?:.' stripped (application_qa.qkey, qbank_wording.norm)."""
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
    if "page" not in [r[1] for r in conn.execute("PRAGMA table_info(application_qa)")]:
        conn.execute("ALTER TABLE application_qa ADD COLUMN page INTEGER")      # which form page asked it
    if "policy_verdict" not in [r[1] for r in conn.execute("PRAGMA table_info(application_qa)")]:
        conn.execute("ALTER TABLE application_qa ADD COLUMN policy_verdict TEXT")   # D-lite: decline/held verdict (qa_recorder)
    if "options_json" not in [r[1] for r in conn.execute("PRAGMA table_info(application_qa)")]:
        conn.execute("ALTER TABLE application_qa ADD COLUMN options_json TEXT")  # a choice field's options
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aqa_job_status ON application_qa(job_id, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aqa_qkey ON application_qa(qkey)")
    conn.execute("CREATE TABLE IF NOT EXISTS agent_settings (key TEXT PRIMARY KEY, value TEXT)")
    # qbank_candidate (Candidate B, closed feedback loop — docs/career-agent/triage/answer-redteam.md §5):
    # PROPOSALS of bank-worthy human answers. Nothing here feeds an answer to the
    # agent and no reader of application_qa/qbank sees this table; only a deliberate
    # operator action (scripts/qbank.py curate --approve) promotes a row into the bank.
    conn.execute("""CREATE TABLE IF NOT EXISTS qbank_candidate (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER, qkey TEXT NOT NULL, label TEXT NOT NULL,
        question_text TEXT NOT NULL, answer TEXT NOT NULL,
        kind TEXT, source TEXT NOT NULL DEFAULT 'human',
        status TEXT NOT NULL DEFAULT 'pending', notes TEXT,
        created_at TEXT, decided_at TEXT,
        UNIQUE(qkey, answer))""")
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
    for k in ("context_json", "unsupported_claims", "candidates_json", "options_json"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d


def open_questions(conn, job_id: int) -> list[dict]:
    """Questions still needing an answer for this job: the newest row per
    question, and only if that newest row is still `needs_answer` (a later run
    that filled it, or a reply, closes it). A later run's row for the same field
    (ref, page) also closes it — its label may read differently now (a raw
    `cards[..][field3]` name the next run perceived as the real question)."""
    ensure(conn)
    cur = conn.execute(
        """SELECT * FROM application_qa a WHERE job_id = ? AND status = 'needs_answer'
           AND id = (SELECT MAX(id) FROM application_qa b
                     WHERE b.job_id = a.job_id AND b.qkey = a.qkey)
           AND NOT EXISTS (SELECT 1 FROM application_qa c WHERE c.job_id = a.job_id AND c.ref = a.ref
                           AND c.page IS a.page AND c.run_key != a.run_key AND c.id > a.id)
           ORDER BY id""", (job_id,))
    return [_row(cur, r) for r in cur.fetchall()]


def prior_answers(conn, job_id: int, exclude_run_key: str | None = None) -> dict:
    """{normalized label: answer} the human already gave for THIS job (Telegram, the tracker, the dashboard) in
    earlier runs, latest wins. A re-run of the same application must not ask the same questions again."""
    rows = conn.execute(
        "SELECT label, answer FROM application_qa WHERE job_id = ? AND status = 'answered' AND source = 'human' "
        "AND answer IS NOT NULL AND TRIM(answer) != '' AND (? IS NULL OR run_key != ?) ORDER BY id", (job_id, exclude_run_key, exclude_run_key)).fetchall()
    return {norm_key(label): answer for label, answer in rows if norm_key(label)}


def open_counts(conn) -> dict[int, int]:
    ensure(conn)
    rows = conn.execute(
        """SELECT job_id, COUNT(*) FROM application_qa a WHERE status = 'needs_answer'
           AND job_id IS NOT NULL
           AND id = (SELECT MAX(id) FROM application_qa b
                     WHERE b.job_id = a.job_id AND b.qkey = a.qkey)
           AND NOT EXISTS (SELECT 1 FROM application_qa c WHERE c.job_id = a.job_id AND c.ref = a.ref
                           AND c.page IS a.page AND c.run_key != a.run_key AND c.id > a.id)
           GROUP BY job_id""").fetchall()
    return {j: n for j, n in rows}


def mark_answered(conn, job_id: int, qkey: str, answer: str, *, keep_source: bool = False) -> int:
    """Close every open row for this job+question. Returns rows changed.
    keep_source=True leaves `source` as-is (e.g. a qbank_likely reply keeps
    its retrieval-band stats true instead of being relabelled 'human')."""
    ensure(conn)
    set_source = "" if keep_source else "source='human', "
    cur = conn.execute(
        f"UPDATE application_qa SET status='answered', answer=?, {set_source}"
        "updated_at=? WHERE job_id=? AND qkey=? AND status='needs_answer'",
        (answer, _now(), job_id, qkey))
    label = None
    if cur.rowcount:      # the replied row carries the label/kind the candidate proposal needs
        label = conn.execute("SELECT label, kind FROM application_qa WHERE job_id=? AND qkey=? "
                             "AND status='answered' ORDER BY id DESC LIMIT 1", (job_id, qkey)).fetchone()
    conn.commit()
    if job_id is not None and label and str(answer or "").strip():
        try:              # a human reply (incl. confirming a bank guess) proposes a bank candidate
            propose_candidate(conn, job_id, label[0], answer, kind=label[1] or "", source="human")
        except Exception as e:
            print(f"[qa] candidate proposal failed: {e!r}", flush=True)
    return cur.rowcount


def resolve_settled_questions(conn) -> int:
    """Retire open questions on jobs that settled while the questions waited.
    A job that is applied / interviewing / offer / rejected / closed will never
    go back to asking, yet its needs_answer rows still count in open_questions,
    open_counts and the stats forever. They flip to 'obsolete' and `basis`
    records why, citing the job's own status. Nothing becomes an answer here:
    `answer` stays NULL and `source` is untouched, so prior_answers never picks
    these rows up — a reconciliation that fabricated answers would poison the
    re-run dedupe. Failed/parked jobs keep their asks (answering the last one
    re-queues the job). Idempotent: only still-open rows change, so it can be
    called on schedule — the submit watcher's reconcile pass does every 30 min.
    Returns the number of rows retired."""
    ensure(conn)
    cur = conn.execute(f"""
        UPDATE application_qa SET status = 'obsolete',
            basis = 'job is ' || (SELECT status FROM jobs WHERE id = application_qa.job_id)
                    || ' — question no longer answerable, resolved obsolete',
            updated_at = ?
        WHERE status = 'needs_answer' AND job_id IS NOT NULL
          AND job_id IN (SELECT id FROM jobs
                         WHERE status IN ({', '.join('?' * len(SETTLED_JOB_STATUSES))}))""",
        (_now(), *SETTLED_JOB_STATUSES))
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


def qbank_confident_min(conn) -> int:
    """Question-bank match score (0-100) at/above which a clear top match fills
    without a review flag. Separate from answer_confidence_min (LLM drafts)."""
    try:
        return max(0, min(100, int(get_setting(conn, "qbank_confident_min"))))
    except (TypeError, ValueError):
        return int(DEFAULT_SETTINGS["qbank_confident_min"])


# ── bank-candidate proposals (Candidate B) ───────────────────────────────────
# A human-typed answer becomes a PENDING qbank_candidate proposal. Candidates are
# write-only for the pipeline — no answer tier, stat or autonomy check reads them;
# only the operator closes the loop (scripts/qbank.py curate --approve/--reject).

_BOOLEAN_ANSWERS = {"y", "n", "yes", "no", "true", "false", "checked", "unchecked", "on", "off"}


def propose_candidate(conn, job_id, label: str, answer, *, kind: str = "", source: str = "human"):
    """The PENDING proposal for one human-typed answer; None = nothing to propose.
    Dedupe: skip when the exact qkey+answer row already exists (UNIQUE(qkey, answer)) or
    when the bank's exact-normalized wording is already answered (a zombie otherwise)."""
    text = str(answer or "").strip()
    question = (label or "").strip()
    if job_id is None or not text or not question:
        return None
    try:      # the bank sees the question without its 'type "X" if …' instruction
        from career_agent.memory.qbank_match import split_escape
        question = split_escape(question)[0] or question
    except Exception:                       # career_agent not importable here: use the label as-is
        pass
    qkey = norm_key(question)
    if not qkey or _bank_answered(conn, qkey):
        return None
    ensure(conn)
    cur = conn.execute(
        "INSERT OR IGNORE INTO qbank_candidate (job_id, qkey, label, question_text, answer, kind, source, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)", (job_id, qkey, (label or "").strip(), question, text, kind or None, source, _now()))
    conn.commit()
    return cur.lastrowid if cur.rowcount else None       # rowcount 0 = dupe of an existing proposal


def _bank_answered(conn, qkey: str) -> bool:
    try:
        return conn.execute(
            "SELECT 1 FROM qbank_wording w JOIN qbank_entry e ON e.id=w.entry_id WHERE w.norm=? "
            "AND e.status='active' AND e.topic IS NOT 'story' AND TRIM(COALESCE(e.answer,'')) != '' LIMIT 1",
            (qkey,)).fetchone() is not None
    except Exception:
        return False     # the bank's tables aren't there yet — nothing can be in the bank


def candidate(conn, cid: int):
    ensure(conn)
    cur = conn.execute("""SELECT c.*, j.title, j.company FROM qbank_candidate c
                          LEFT JOIN jobs j ON j.id = c.job_id WHERE c.id=?""", (cid,))
    r = cur.fetchone()
    return dict(zip([d[0] for d in cur.description], r)) if r else None


def pending_candidates(conn) -> list[dict]:
    """Pending proposals with the job they came from, oldest first."""
    ensure(conn)
    cur = conn.execute("""SELECT c.*, j.title, j.company FROM qbank_candidate c
                          LEFT JOIN jobs j ON j.id = c.job_id
                          WHERE c.status='pending' ORDER BY c.id""")
    return [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]


def set_candidate_status(conn, cid: int, status: str, notes: str = "") -> bool:
    """pending -> approved/rejected only; notes keep the reason. A re-replied
    answer re-proposes automatically, so nothing can go back to pending."""
    if status not in ("approved", "rejected"):
        raise ValueError(status)
    ensure(conn)
    cur = conn.execute("UPDATE qbank_candidate SET status=?, decided_at=?, "
                       "notes=CASE WHEN ? != '' THEN ? ELSE notes END WHERE id=? AND status='pending'",
                       (status, _now(), notes, notes, cid))
    conn.commit()
    return cur.rowcount > 0


def promote_candidate(conn, cid: int, embed=None) -> dict:
    """Approve ONE pending candidate into the bank through the exact path a human answer
    enters today (qbank_promote.promote_answer: wording rows, approvals, dedupe).
    The guards REJECT with the reason on failure; no bulk import — one row per call."""
    ensure(conn)
    c = candidate(conn, cid)
    if c is None:
        return {"promoted": False, "reason": f"no candidate {cid}"}
    if c["status"] != "pending":
        return {"promoted": False, "reason": f"candidate {cid} is {c['status']}, not pending"}
    reason = _candidate_guard_reason(conn, c)
    if reason:
        set_candidate_status(conn, cid, "rejected", reason)
        return {"promoted": False, "reason": reason}
    try:
        from career_agent.memory.qbank_promote import promote_answer
        field = types.SimpleNamespace(label=c["question_text"], kind=c["kind"] or "text", description="", ref="#candidate")
        eid = promote_answer(conn, field, c["answer"], embed)
    except Exception as e:                  # a dead embedder/bank must not wedge the row pending
        return {"promoted": False, "reason": f"bank promote failed: {e!r}"}
    if eid is None:                         # the bank's own guards (company-specific/sensitive) refused
        reason = "bank refused the promote (company-specific or sensitive question)"
        set_candidate_status(conn, cid, "rejected", reason)
        return {"promoted": False, "reason": reason}
    note = f"promoted to qbank entry {eid}"
    set_candidate_status(conn, cid, "approved", note)
    return {"promoted": True, "entry_id": eid, "reason": note}


def _candidate_guard_reason(conn, c: dict) -> str:
    """'' = promotable. The display `label` may carry the 'type "X" if …' sentence;
    question_text is what promotion saves, so IT must match the key (red-team §5:
    exact-normalized matching, shaped values, bank dedupe)."""
    question = c["question_text"]
    answer = (c["answer"] or "").strip()
    if norm_key(question) != c["qkey"]:
        return (f"question {question[:60]!r} does not normalize to its key "
                f"{c['qkey']!r} — exact-normalized matching required")
    if not answer:
        return "empty answer"
    if answer.lower() in _BOOLEAN_ANSWERS:
        return ("boolean-ambiguous answer: the bank stores shaped values for this "
                "question — save the wording with its option list on the dashboard instead")
    try:
        from career_agent.memory.qbank_rules import infer_shape, shape_ok
        shape = infer_shape(None, "", "", question)
        if shape and not shape_ok(shape, answer):
            return (f"answer {answer[:40]!r} does not fit the {shape} shape the question "
                    "asks for — not promotable unshaped")
    except Exception:                       # shape tier optional: don't block curate on it
        pass
    if _bank_answered(conn, c["qkey"]):
        return "bank already answers this question (its entry is never overwritten)"
    return ""


# ── review + retrieval analytics ─────────────────────────────────────────────

_MEMORY = ("learned", "semantic", "qbank", "qbank_likely")   # sources meaning "memory answered this"


def answers_used(conn, job_id: int) -> list[dict]:
    """What the agent filled for this job (newest row per question), so each
    can be reviewed: was the retrieved answer right?"""
    ensure(conn)
    cur = conn.execute(
        """SELECT * FROM application_qa a WHERE job_id = ? AND status IN ('filled', 'answered')
           AND id = (SELECT MAX(id) FROM application_qa b WHERE b.job_id = a.job_id AND b.qkey = a.qkey)
           ORDER BY id""", (job_id,))
    return [_row(cur, r) for r in cur.fetchall()]


def origin(row: dict) -> str:
    """Where an answer came from, for the tracker's run view:
    saved_exact / saved (your Answers), similar (a best guess from a similar saved
    question), model (written by the model), profile (your profile / standard
    rules), board (prefilled by the job board), you (typed by you), open (no answer)."""
    src, status = row.get("source"), row.get("status")
    if src == "qbank_likely":
        return "similar"
    if status == "needs_answer":
        return "open"
    if src in ("qbank", "learned"):
        return "saved_exact" if row.get("retrieval_kind") == "exact" else "saved"
    return {"judgment": "model", "human": "you", "board_prefill": "board"}.get(src, "profile")


def questions_by_page(conn, job_id: int) -> dict:
    """The latest run's questions grouped by form page ({page|None: [question]}),
    in the order they were asked. Each carries its origin, the saved question it
    matched, and for model drafts the confidence, basis and prompt used."""
    ensure(conn)
    cur = conn.execute("""SELECT * FROM application_qa WHERE job_id = ? AND run_key =
                          (SELECT run_key FROM application_qa WHERE job_id = ? ORDER BY id DESC LIMIT 1)
                          ORDER BY id""", (job_id, job_id))
    out: dict = {}
    for r in cur.fetchall():
        d = _row(cur, r)
        ctx = d.get("context_json")
        out.setdefault(d.get("page"), []).append({
            "id": d["id"], "label": d["label"], "kind": d["kind"], "answer": d["answer"], "source": d["source"],
            "status": d["status"], "origin": origin(d), "matched": d["retrieved_qkey"],
            "match_kind": d["retrieval_kind"], "score": d["retrieval_score"], "confidence": d["confidence"],
            "basis": d["basis"], "unsupported_claims": d["unsupported_claims"] or [],
            "prompt": ctx.get("prompt") if isinstance(ctx, dict) else None, "outcome": d["outcome"],
            "lessons": (ctx.get("lessons") if isinstance(ctx, dict) else None) or []})
    return out


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
    bands = q("""SELECT MIN(CAST(retrieval_score * 10 AS INT), 9), SUM(outcome='kept'), SUM(outcome='edited')
                 FROM application_qa WHERE source IN ('qbank', 'qbank_likely')
                 AND retrieval_score IS NOT NULL AND outcome IS NOT NULL GROUP BY 1 ORDER BY 1""")
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
        "by_band": [{"band": f"{b / 10:.1f}–{(b + 1) / 10:.1f}", "kept": k or 0, "edited": e or 0,
                     "edit_rate": round((e or 0) / ((k or 0) + (e or 0)), 3)} for b, k, e in bands],
    }


def recent_retrievals(conn, limit: int = 50) -> list[dict]:
    ensure(conn)
    cur = conn.execute(
        """SELECT a.id, a.job_id, j.title, j.company, a.label, a.answer, a.source, a.status, a.confidence,
                  a.retrieval_kind, a.retrieved_qkey, a.retrieval_score, a.candidates_json, a.outcome, a.created_at
           FROM application_qa a LEFT JOIN jobs j ON j.id = a.job_id
           ORDER BY a.id DESC LIMIT ?""", (max(1, min(limit, 200)),))
    return [_row(cur, r) for r in cur.fetchall()]
