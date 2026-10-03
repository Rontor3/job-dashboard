"""Daily Gmail scan: follow the companies we applied to.

For every job in Applied/Interviewing, look for mail whose sender name, subject
or sender domain carries the company name (or that comes from a sender we
already learned for that job). Only matching mail is opened; the local LLM
(keyword rules as fallback) classifies it and the job's tracker status moves:
interview -> Interviewing (+ round), offer -> Selected, rejected -> Rejected.
Read-only on Gmail. Everything is recorded in `job_mail` so a message is
handled once and the tracker can show what each company wrote.
"""
from __future__ import annotations

import base64
import re
import time
from email.utils import parseaddr

from job_dashboard import qa_store, tracker
from job_dashboard.mail_classify import classify

DAY = 86400
FIRST_LOOKBACK_DAYS = 30
SCANNED = ("applied", "interviewing")
_FINAL = ("offer", "rejected")
_LEGAL = {"inc", "ltd", "llc", "pvt", "private", "limited", "technologies", "technology", "labs", "lab",
          "solutions", "corp", "corporation", "co", "group", "india", "systems", "software", "services", "the"}
# Job boards write about everyone; their mail counts only when it carries a decision.
_BOARDS = ("naukri.com", "linkedin.com", "indeed.com", "instahyre.com", "iimjobs.com", "wellfound.com",
           "glassdoor.com", "ycombinator.com", "workatastartup.com", "foundit.in", "monster.com")
_FREE = ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "proton.me")
_DECISIVE = ("interview", "offer", "rejected", "assessment")


def ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS job_mail (
        id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL, message_id TEXT NOT NULL UNIQUE,
        received_at INTEGER, sender TEXT, subject TEXT, snippet TEXT,
        category TEXT, round INTEGER, summary TEXT, classified_by TEXT, created_at INTEGER)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_mail_job ON job_mail(job_id, received_at)")
    conn.execute("CREATE TABLE IF NOT EXISTS job_sender (job_id INTEGER PRIMARY KEY, email TEXT NOT NULL)")
    conn.commit()


# ---- matching --------------------------------------------------------------
def _tokens(company: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", (company or "").lower())
    kept = [w for w in words if w not in _LEGAL]
    return kept or words


def _company_re(company: str):
    toks = _tokens(company)
    if len("".join(toks)) < 3:
        return None
    return re.compile(r"(?<![a-z0-9])" + r"[\s._-]*".join(map(re.escape, toks)) + r"(?![a-z0-9])", re.I)


def _domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def _is_board(email: str) -> bool:
    d = _domain(email)
    return any(d == b or d.endswith("." + b) for b in _BOARDS)


def _pick(cands: list[dict], subject: str) -> dict:
    """Several jobs at one company: the one whose title the subject names, else the newest."""
    low = (subject or "").lower()
    named = [c for c in cands if c["title"] and c["title"].lower() in low]
    pool = named or cands
    return max(pool, key=lambda c: c["since"] or 0)


def match_job(jobs: list[dict], senders: dict[int, str], name: str, email: str, subject: str):
    haystack = f"{name} {subject} {_domain(email).rsplit('.', 1)[0]}"
    by_name = [j for j in jobs if (rx := j["rx"]) is not None and rx.search(haystack)]
    by_sender = [j for j in jobs if senders.get(j["id"]) and senders[j["id"]] == email.lower()]
    cands = by_name or by_sender
    return _pick(cands, subject) if cands else None


# ---- store -----------------------------------------------------------------
def sender_for_job(conn, job_id: int):
    r = conn.execute("SELECT email FROM job_sender WHERE job_id = ?", (job_id,)).fetchone()
    return r[0] if r else None


def mail_for_job(conn, job_id: int) -> list[dict]:
    ensure(conn)
    cur = conn.execute("""SELECT id, message_id, received_at, sender, subject, snippet, category, round, summary,
                                 classified_by FROM job_mail WHERE job_id = ? ORDER BY received_at DESC""", (job_id,))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def is_due(conn, now: float | None = None) -> bool:
    return (now or time.time()) - int(qa_store.get_setting(conn, "mail_last_scan")) >= DAY


def _candidates(conn) -> list[dict]:
    marks = ",".join("?" * len(SCANNED))
    rows = conn.execute(f"""SELECT id, company, title, status, interview_round, status_updated_at FROM jobs
                            WHERE duplicate_of IS NULL AND status IN ({marks})""", SCANNED).fetchall()
    return [{"id": r[0], "company": r[1], "title": r[2], "status": r[3], "round": r[4],
             "since": r[5], "rx": _company_re(r[1])} for r in rows]


def _move(conn, job: dict, result: dict) -> str:
    """Apply a classified mail to the job's tracker status; returns the status after."""
    cat, cur = result["category"], job["status"]
    if cur in _FINAL:
        return cur
    if cat == "rejected":
        tracker.set_status(conn, job["id"], "rejected")
        return "rejected"
    if cat == "offer":
        tracker.set_status(conn, job["id"], "offer")
        return "offer"
    if cat == "interview":
        have = job["round"] if cur == "interviewing" else 0
        rnd = max(result["round"] or 1, have or 1)
        tracker.set_status(conn, job["id"], "interviewing", round=rnd)
        return "interviewing"
    return cur


def run_scan(conn, box, llm, now: float | None = None) -> dict:
    """Scan the mailbox `box` (search(since)/body(id)); never raises."""
    now = int(now or time.time())
    out = {"scanned": 0, "matched": 0, "changes": [], "error": None}
    ensure(conn)
    if box is None:
        out["error"] = "gmail_not_connected"
        return out
    last = int(qa_store.get_setting(conn, "mail_last_scan"))
    since = now - FIRST_LOOKBACK_DAYS * DAY if last == 0 else last - DAY        # a day of overlap; message ids dedupe
    try:
        jobs = _candidates(conn)
        senders = {r[0]: r[1] for r in conn.execute("SELECT job_id, email FROM job_sender")}
        msgs = box.search(since) if jobs else []
        out["scanned"] = len(msgs)
        for m in msgs:
            name, email = parseaddr(m.get("sender") or "")
            email = email.lower()
            if conn.execute("SELECT 1 FROM job_mail WHERE message_id = ?", (m["id"],)).fetchone():
                continue
            job = match_job(jobs, senders, name, email, m.get("subject") or "")
            if job is None:
                continue
            body = box.body(m["id"]) or m.get("snippet") or ""
            result = classify(llm, m.get("subject") or "", body, company=job["company"], title=job["title"])
            if _is_board(email) and result["category"] not in _DECISIVE:
                continue                                    # a job-board newsletter that merely names the company
            conn.execute("""INSERT INTO job_mail (job_id, message_id, received_at, sender, subject, snippet, category,
                                                  round, summary, classified_by, created_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                         (job["id"], m["id"], m.get("received"), m.get("sender"), m.get("subject"),
                          (m.get("snippet") or "")[:300], result["category"], result["round"], result["summary"],
                          result["by"], now))
            if (email and job["id"] not in senders and not _is_board(email) and _domain(email) not in _FREE):
                conn.execute("INSERT OR IGNORE INTO job_sender (job_id, email) VALUES (?, ?)", (job["id"], email))
                senders[job["id"]] = email                  # follow this sender from now on
            after = _move(conn, job, result)
            job["status"] = after
            if after == "interviewing":
                job["round"] = conn.execute("SELECT interview_round FROM jobs WHERE id = ?", (job["id"],)).fetchone()[0]
            conn.commit()
            out["matched"] += 1
            out["changes"].append({"job_id": job["id"], "company": job["company"], "category": result["category"],
                                   "status": after, "subject": m.get("subject")})
        qa_store.set_setting(conn, "mail_last_scan", now)
    except Exception as e:
        out["error"] = type(e).__name__
    return out


# ---- Gmail adapter -----------------------------------------------------------
def _header(msg: dict, name: str) -> str:
    return next((h["value"] for h in msg.get("payload", {}).get("headers", []) if h["name"].lower() == name), "")


def _text_of(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"] + "==").decode("utf-8", errors="replace")
    for part in payload.get("parts") or []:
        text = _text_of(part)
        if text:
            return text
    return ""


class GmailMailbox:
    """Read-only Gmail (the same token career_agent uses for OTPs)."""

    def __init__(self, service):
        self.service = service

    def search(self, since_epoch: int, max_messages: int = 300) -> list[dict]:
        users = self.service.users().messages()
        ids, token = [], None
        while len(ids) < max_messages:
            resp = users.list(userId="me", q=f"after:{since_epoch} -from:me -category:promotions -category:social",
                              maxResults=100, pageToken=token).execute()
            ids += [m["id"] for m in resp.get("messages", [])]
            token = resp.get("nextPageToken")
            if not token:
                break
        out = []
        for mid in ids[:max_messages]:
            m = users.get(userId="me", id=mid, format="metadata", metadataHeaders=["From", "Subject"]).execute()
            out.append({"id": mid, "sender": _header(m, "from"), "subject": _header(m, "subject"),
                        "snippet": m.get("snippet", ""), "received": int(m.get("internalDate", 0)) // 1000})
        return out

    def body(self, msg_id: str) -> str:
        m = self.service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        return _text_of(m.get("payload", {})) or m.get("snippet", "")


def default_mailbox():
    """A GmailMailbox if the token exists, else None."""
    try:
        from career_agent.integrations.gmail_otp import _build_service, available
        return GmailMailbox(_build_service()) if available() else None
    except Exception:
        return None
