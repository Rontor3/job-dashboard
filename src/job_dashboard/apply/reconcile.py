"""Mark tracked jobs applied from your confirmation emails.

The tracker only learned of a submit when the agent clicked it or the watcher saw the tab. This works from the other end:
the confirmation emails already in your inbox. Each email is matched to ONE tracked job — by company and role words, else by
which job the agent was working on just before the email arrived (a LinkedIn email names the company, not the role).
Anything it cannot place with certainty is reported as ambiguous and left alone."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from career_agent.integrations.gmail_confirm import _TITLE_NOISE, _tokens, company_in
from job_dashboard import autonomy
from job_dashboard.db import set_job_status

WINDOW = timedelta(hours=36)          # the agent worked on the job within this long before the email arrived


def _parse(ts: str):
    try:
        d = datetime.fromisoformat(ts)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _worked_on(conn, job_id: int, when: datetime) -> bool:
    for (ts,) in conn.execute("SELECT COALESCE(finished_at, started_at) FROM apply_queue WHERE job_id=?", (job_id,)):
        d = _parse(ts)
        if d and when - WINDOW <= d <= when + timedelta(minutes=5):
            return True
    return False


def _status_near(conn, job_id: int, when: datetime) -> bool:
    """The job was marked applied around the time of the email (the queue row may have been overwritten by a later run)."""
    r = conn.execute("SELECT status_updated_at FROM jobs WHERE id=?", (job_id,)).fetchone()
    d = _parse(r[0]) if r and r[0] else None
    return bool(d and when - WINDOW <= d <= when + WINDOW)


def match_job(conn, msg: dict, jobs: list, all_jobs: list | None = None):
    """(job_id | None, why). `jobs` = [(id, company, title, status)] of jobs not yet applied; `all_jobs` = every tracked job
    (applied ones too), so "the only job at that company" is judged against all of them."""
    hay = f"{msg.get('subject', '')} {msg.get('snippet', '')} {msg.get('from', '')}".lower()
    when = _parse(msg.get("date", ""))
    accounted = [j for j in (all_jobs or []) if j[3] == "applied" and company_in(msg, j[1]) and when and (_worked_on(conn, j[0], when) or _status_near(conn, j[0], when))]
    if accounted:
        return None, "already tracked as applied"           # an applied job at that company, dated around this email, explains it
    cands = [(jid, title) for jid, company, title, status in jobs if company_in(msg, company)]
    if not cands:
        return None, "no tracked job at that company"
    role = lambda t: [x for x in _tokens(t, _TITLE_NOISE)]
    strong = [jid for jid, t in cands if len(role(t)) >= 2 and sum(x in hay for x in role(t)) >= max(2, len(role(t)) - 1)]
    if len(strong) == 1:
        return strong[0], "company and role words in the email"
    recent = [jid for jid, _ in cands if when and _worked_on(conn, jid, when)]
    if len(recent) == 1:
        return recent[0], "the agent worked on this job just before the email"
    everyone = [j for j in (all_jobs if all_jobs is not None else jobs) if company_in(msg, j[1])]
    if len(cands) == 1 and len(everyone) == 1:
        return cands[0][0], "the only tracked job at that company"
    return None, f"{len(cands)} tracked jobs at that company and nothing to tell them apart"


def reconcile(conn, messages: list, apply: bool = True) -> dict:
    """Match confirmation `messages` to tracked jobs; mark the certain ones applied. Returns {matched, ambiguous, unmatched}."""
    autonomy.ensure(conn)
    jobs = conn.execute("SELECT id, company, title, status, job_url FROM jobs WHERE duplicate_of IS NULL "
                        "AND (status IS NULL OR status IN ('', 'saved', 'failed'))").fetchall()
    open_jobs = [(j[0], j[1] or "", j[2] or "", j[3]) for j in jobs]
    everyone = [(r[0], r[1] or "", r[2] or "", r[3]) for r in conn.execute(
        "SELECT id, company, title, status FROM jobs WHERE duplicate_of IS NULL")]
    url_of = {j[0]: j[4] for j in jobs}
    matched, ambiguous, untracked, already, taken = [], [], [], 0, set()
    seen = {r[0] for r in conn.execute("SELECT msg_id FROM reconciled_mail")}
    for msg in sorted(messages, key=lambda m: m.get("date", "")):
        if msg.get("id") in seen:
            continue                                          # this email already told us about a job
        jid, why = match_job(conn, msg, [j for j in open_jobs if j[0] not in taken], everyone)
        if jid is None:
            if "nothing to tell" in why:
                ambiguous.append({"subject": msg.get("subject"), "from": msg.get("from"), "date": msg.get("date"), "why": why})
            elif why == "already tracked as applied":
                already += 1
            else:
                untracked.append({"subject": msg.get("subject"), "from": msg.get("from"), "date": msg.get("date")})
            continue
        taken.add(jid)
        row = {"job_id": jid, "subject": msg.get("subject"), "from": msg.get("from"), "date": msg.get("date"), "why": why}
        matched.append(row)
        if apply:
            set_job_status(conn, jid, "applied")
            if msg.get("id"):
                conn.execute("INSERT OR IGNORE INTO reconciled_mail (msg_id, job_id, subject, matched_at) VALUES (?,?,?,?)",
                             (msg["id"], jid, msg.get("subject"), datetime.now(timezone.utc).isoformat()))
                conn.commit()
            if not conn.execute("SELECT 1 FROM submit_history WHERE job_id=?", (jid,)).fetchone():
                autonomy.record_submission(conn, jid, "", {}, "manual", url_of.get(jid) or "")
    return {"matched": matched, "ambiguous": ambiguous, "untracked": untracked, "already_applied": already,
            "unmatched": len(untracked)}
