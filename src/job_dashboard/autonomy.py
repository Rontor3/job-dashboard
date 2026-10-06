"""Graduated autonomy: an answer earns the right to be submitted without you.

An answer from the question bank starts with 0 approvals. Each time a form is submitted with that answer left as the
agent filled it (you submitted it, or you approved it over Telegram), the entry gains an approval; an edit resets it to 0.
At AUTONOMY_THRESHOLD approvals the answer is autonomous. A form may be submitted without you only when EVERY answer on it
is autonomous (or comes from your fixed profile) — see `autonomy_report` — and only where that site has already had a
confirmed submit (`has_confirmed_submit`): the first submit on a new kind of form always goes through you.

Spec: docs/superpowers/specs/2026-08-22-career-agent-design.md §8 (this replaces the semantic-vault counter the
question bank superseded)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from job_dashboard import qa_store

AUTONOMY_THRESHOLD = 3
# Decision sources that are your own fixed facts or something you gave this very run: never a guess.
STABLE_SOURCES = {"resume", "standard", "attestation", "human", "human_prior", "profile", "board_prefill", "upload"}


def ensure(conn) -> None:
    qa_store.ensure(conn)
    conn.execute("""CREATE TABLE IF NOT EXISTS submit_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER, ats_key TEXT NOT NULL,
        how TEXT NOT NULL, confirmed_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS reconciled_mail (
        msg_id TEXT PRIMARY KEY, job_id INTEGER, subject TEXT, matched_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS submission_watch (
        job_id INTEGER PRIMARY KEY, url TEXT NOT NULL, run_key TEXT, last_values TEXT, created_at TEXT NOT NULL,
        tab_id TEXT)""")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(submission_watch)")]
    if "tab_id" not in cols:
        conn.execute("ALTER TABLE submission_watch ADD COLUMN tab_id TEXT")
    if "how" not in cols:
        conn.execute("ALTER TABLE submission_watch ADD COLUMN how TEXT")      # 'auto' when the agent clicked Submit and got no proof
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='qbank_entry'").fetchone() \
            and "approvals" not in [r[1] for r in conn.execute("PRAGMA table_info(qbank_entry)")]:
        conn.execute("ALTER TABLE qbank_entry ADD COLUMN approvals INTEGER NOT NULL DEFAULT 0")
    conn.commit()


def key(label) -> str:
    """The form-side name of a question, comparable between what was filled and what was read back ('Source*' == 'source')."""
    return qa_store.norm_key(str(label or "").replace("*", "").replace("✱", ""))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ats_key(url: str) -> str:
    """The kind of site a submit happened on: the board for job boards, else the host (jobs.siemens.com, ...)."""
    host = (urlparse(url or "").hostname or "").lower()
    for board in ("linkedin.com", "indeed.com", "naukri.com", "wellfound.com", "iimjobs.com", "instahyre.com"):
        if host.endswith(board):
            return board
    return host


def approvals(conn, entry_id: str) -> int:
    ensure(conn)
    r = conn.execute("SELECT approvals FROM qbank_entry WHERE id=?", (entry_id,)).fetchone()
    return int(r[0] or 0) if r else 0


def is_autonomous_entry(conn, entry_id: str) -> bool:
    return approvals(conn, entry_id) >= AUTONOMY_THRESHOLD


def _set(conn, entry_id: str, n: int) -> None:
    conn.execute("UPDATE qbank_entry SET approvals=? WHERE id=?", (n, entry_id))


def _same(answer, final) -> bool:
    norm = lambda v: re.sub(r"\s+", " ", str(v if v is not None else "").strip().lower()).strip(" .")
    a, f = norm(answer), norm(final)
    if a in ("true", "yes", "checked") and f in ("true", "yes", "checked", "on"):
        return True
    return a == f or (bool(a) and (a in f or f in a) and min(len(a), len(f)) >= 3)      # "30 days" vs "30"


def record_submission(conn, job_id: int, run_key: str, final_values: dict, how: str, url: str = "") -> dict:
    """A confirmed submit: turn it into approvals. `final_values` = {normalized label: value on the form just before it
    was submitted}. Unchanged -> +1 approval for the answer's bank entry; changed -> 0 (and the row is marked edited).
    Also files the submit in the history, which is what lets that kind of site auto-submit later."""
    ensure(conn)
    approved = edited = 0
    rows = conn.execute("SELECT id, label, answer, source, retrieved_qkey FROM application_qa "
                        "WHERE run_key=? AND status IN ('filled','answered') AND answer IS NOT NULL", (run_key,)).fetchall()
    for rid, label, answer, source, entry in rows:
        k = key(label)
        if k not in final_values:
            continue                                      # could not read it back: neither an approval nor an edit
        if _same(answer, final_values[k]):
            qa_store.set_outcome(conn, rid, "kept")
            if entry and source in ("qbank", "qbank_likely"):
                _set(conn, entry, approvals(conn, entry) + 1)
            approved += 1
        else:
            qa_store.set_outcome(conn, rid, "edited")
            if entry:
                _set(conn, entry, 0)
            edited += 1
    conn.execute("INSERT INTO submit_history (job_id, ats_key, how, confirmed_at) VALUES (?,?,?,?)",
                 (job_id, ats_key(url), how, _now()))
    conn.commit()
    return {"approved": approved, "edited": edited}


def has_confirmed_submit(conn, key: str) -> bool:
    ensure(conn)
    return conn.execute("SELECT 1 FROM submit_history WHERE ats_key=? LIMIT 1", (key,)).fetchone() is not None


def auto_submits_last_day(conn) -> int:
    ensure(conn)
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    return conn.execute("SELECT COUNT(*) FROM submit_history WHERE how='auto' AND confirmed_at > ?", (since,)).fetchone()[0]


def autonomy_report(conn, run_key: str, decisions) -> dict:
    """{ok, blockers: [(label, why)], confident, total}: may this filled form go out without a human?"""
    ensure(conn)
    entry_of = {ref: q for ref, q in conn.execute("SELECT ref, retrieved_qkey FROM application_qa WHERE run_key=?", (run_key,))}
    blockers, total = [], 0
    for d in decisions:
        value = d.get("value") if isinstance(d, dict) else getattr(d, "value", None)
        if value is None:
            continue
        get = (lambda k: d.get(k)) if isinstance(d, dict) else (lambda k: getattr(d, k, None))
        total += 1
        source, label, ref = get("source"), get("label") or get("ref"), get("ref")
        if source in STABLE_SOURCES:
            continue
        if source == "qbank":
            entry = entry_of.get(ref)
            n = approvals(conn, entry) if entry else 0
            if entry and n >= AUTONOMY_THRESHOLD:
                continue
            blockers.append((label, f"{entry or 'answer'}: {n}/{AUTONOMY_THRESHOLD} approvals"))
        else:
            blockers.append((label, f"{source or 'unknown source'}: not a confirmed answer"))
    return {"ok": not blockers, "blockers": blockers, "confident": total - len(blockers), "total": total}


DEFAULT_DAILY_CAP = 5


def autosubmit_policy(conn, url: str, run_key: str, decisions) -> dict:
    """May this filled form be submitted without a human? {allow, reasons, report, site, switch}. `reasons` says why not.
    All must hold: the switch for the site the agent is ON NOW (not the page it started from) is on; every answer is
    autonomous; that kind of site has had a confirmed submit before (the first one is always yours); the daily cap of
    automatic submits is not used up."""
    from job_dashboard.apply.queue_runner import autosubmit_key       # same site -> switch mapping the dashboard uses
    ensure(conn)
    switch_key = autosubmit_key(url)
    try:
        switch_on = qa_store.get_setting(conn, switch_key) == "1"
    except KeyError:
        switch_on = False
    report = autonomy_report(conn, run_key, decisions)
    site = ats_key(url)
    try:
        cap = int(qa_store.get_setting(conn, "autosubmit_daily_cap"))
    except (KeyError, ValueError):
        cap = DEFAULT_DAILY_CAP
    used = auto_submits_last_day(conn)
    reasons = []
    if not switch_on:
        reasons.append(f"auto-submit is off for {switch_key.removeprefix('autosubmit_')}")
    if not report["ok"]:
        reasons.append(f"{len(report['blockers'])} answer(s) not yet autonomous: "
                       + "; ".join(f"{label} ({why})" for label, why in report["blockers"][:4]))
    if not has_confirmed_submit(conn, site):
        reasons.append(f"first submit on {site} must go through you")
    if used >= cap:
        reasons.append(f"daily cap reached ({used}/{cap} automatic submits in 24h)")
    return {"allow": not reasons, "reasons": reasons, "report": report, "site": site, "switch": switch_key, "used": used, "cap": cap}
