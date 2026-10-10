"""The only way the app reads mail. Gmail's read-only scope covers the whole mailbox, so the limits live here.

Every reader (sign-in codes, application confirmations, lockout checks, the daily tracker scan) goes through a Gate:

  * Senders: a search is always ANDed with an allowlist: job boards, applicant-tracking systems, the companies you
    applied to, and whatever you add in the setting `mail_allowed_senders` (comma-separated domains). There is no
    "any unread mail" fallback.
  * Second check: before any header or body is returned, the message's From is checked against the same allowlist,
    so a query Gmail reads loosely can't widen what we see.
  * Window: no search reaches back more than MAX_LOOKBACK_DAYS.
  * Least data: headers and Gmail's snippet by default; a body only on request, capped at MAX_BODY characters.
  * Read-only in practice too: the Gate has no way to label, mark read, move or send.
  * Audit: each message touched is logged to data/logs/mail-access.log (time, purpose, message id, sender domain,
    read or refused); never a subject, body or code.
"""
from __future__ import annotations

import base64
import time
from datetime import datetime, timezone
from email.utils import parseaddr

from job_dashboard import paths

MAX_LOOKBACK_DAYS = 45
MAX_BODY = 20_000
AUDIT = paths.DATA_DIR / "logs" / "mail-access.log"

BOARDS = ("linkedin.com", "naukri.com", "indeed.com", "instahyre.com", "iimjobs.com", "wellfound.com", "angel.co",
          "glassdoor.com", "ycombinator.com", "workatastartup.com", "foundit.in", "monster.com", "hirist.tech",
          "cutshort.io", "unstop.com", "hackerrank.com", "hackerearth.com", "codility.com", "mettl.com")
ATS = ("greenhouse.io", "greenhouse-mail.io", "lever.co", "hire.lever.co", "workday.com", "myworkday.com",
       "myworkdayjobs.com", "icims.com", "smartrecruiters.com", "ashbyhq.com", "jobvite.com", "taleo.net",
       "oracle.com", "oraclecloud.com", "successfactors.com", "successfactors.eu", "sapsf.com", "darwinbox.in",
       "darwinbox.io", "eightfold.ai", "phenom.com", "keka.com", "zohorecruit.com", "zoho.com", "freshteam.com",
       "recruitee.com", "workable.com", "breezy.hr", "bamboohr.com", "jazzhr.com", "teamtailor.com", "personio.de",
       "rippling.com", "gem.com", "beamery.com", "avature.net", "infosys.com", "qualcomm.com", "turing.com")


def _clean(domain: str) -> str:
    return domain.strip().lower().lstrip("@").removeprefix("www.")


def allowed_senders(conn=None, companies: list[str] | tuple = ()) -> list[str]:
    """Boards, tracking systems, your applied-to companies (as name tokens) and the setting's extra domains."""
    extra = [d for d in (_clean(x) for x in _setting(conn).split(",")) if d]
    names = [t for t in (company_token(c) for c in companies) if t]
    return list(dict.fromkeys([*BOARDS, *ATS, *extra, *names]))


def _setting(conn) -> str:
    """`mail_allowed_senders`, from this connection or the app's database; '' when there is none."""
    try:
        from job_dashboard import qa_store
        if conn is not None:
            return qa_store.get_setting(conn, "mail_allowed_senders") or ""
        import sqlite3
        if not paths.DB.is_file():
            return ""
        c = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
        try:
            row = c.execute("SELECT value FROM agent_settings WHERE key='mail_allowed_senders'").fetchone()
            return row[0] if row else ""
        finally:
            c.close()
    except Exception:                                      # noqa: BLE001 — no settings table yet
        return ""


_LEGAL = {"inc", "ltd", "llc", "pvt", "private", "limited", "technologies", "technology", "labs", "lab", "solutions",
          "corp", "corporation", "co", "group", "india", "systems", "software", "services", "the", "ai"}


def company_token(company: str) -> str | None:
    """'Razorpay Software Pvt Ltd' -> 'razorpay': matched against the sender's domain labels."""
    import re
    words = [w for w in re.findall(r"[a-z0-9]+", (company or "").lower()) if w not in _LEGAL]
    tok = "".join(words[:2]) if words else ""
    return tok if len(tok) >= 4 else None


def sender_allowed(from_header: str, senders: list[str]) -> bool:
    """The From address's domain is an allowed domain (or under it), or a company token is one of its labels."""
    _name, addr = parseaddr(from_header or "")
    if "@" not in addr:
        return False
    domain = _clean(addr.rsplit("@", 1)[1])
    labels = domain.replace("-", "").split(".")
    for s in senders:
        if "." in s:
            if domain == s or domain.endswith("." + s):
                return True
        elif s in labels or any(lbl.startswith(s) for lbl in labels[:-1]):
            return True
    return False


def _query_senders(senders: list[str]) -> str:
    return "{" + " ".join(f"from:{s}" for s in senders) + "}"


def _header(msg: dict, name: str) -> str:
    return next((h["value"] for h in msg.get("payload", {}).get("headers", []) if h.get("name", "").lower() == name.lower()), "")


def _text_of(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"] + "==").decode("utf-8", errors="replace")
    for part in payload.get("parts") or []:
        text = _text_of(part)
        if text:
            return text
    return ""


class Gate:
    """Allowlisted, metadata-first, audited reads over one Gmail service."""

    def __init__(self, service, senders: list[str], purpose: str, now=time.time):
        if not senders:
            raise ValueError("a mail gate needs an allowlist")
        self._svc = service
        self.senders = list(senders)
        self.purpose = purpose
        self._now = now
        self._ok: dict[str, list[str]] = {}               # message id -> the allowlist it was listed under

    def _audit(self, msg_id: str, from_header: str, action: str) -> None:
        _n, addr = parseaddr(from_header or "")
        domain = addr.rsplit("@", 1)[-1].lower() if "@" in addr else "?"
        try:
            AUDIT.parent.mkdir(parents=True, exist_ok=True)
            with AUDIT.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}\t{self.purpose}\t{msg_id}\t{domain}\t{action}\n")
        except OSError:
            pass

    def search(self, terms: str = "", since: int | None = None, max_messages: int = 50,
               headers: tuple = ("From", "Subject", "Date"), extra_senders: list[str] | tuple = ()) -> list[dict]:
        """Allowed mail matching `terms` since `since`: {id, sender, subject, date, snippet, received}."""
        floor = int(self._now()) - MAX_LOOKBACK_DAYS * 86400
        since = max(int(since or floor), floor)
        senders = list(dict.fromkeys([*self.senders, *(_clean(s) for s in extra_senders if s)]))
        q = f"after:{since} -from:me -in:chats -in:sent -in:drafts {_query_senders(senders)}" + (f" ({terms})" if terms else "")
        users = self._svc.users().messages()
        ids, token = [], None
        while len(ids) < max_messages:
            resp = users.list(userId="me", q=q, maxResults=min(100, max_messages), pageToken=token).execute()
            ids += [m["id"] for m in resp.get("messages", [])]
            token = resp.get("nextPageToken")
            if not token:
                break
        out = []
        for mid in ids[:max_messages]:
            m = users.get(userId="me", id=mid, format="metadata", metadataHeaders=list(headers)).execute()
            sender = _header(m, "From")
            ok = sender_allowed(sender, senders)
            if ok:
                self._ok[mid] = senders
            self._audit(mid, sender, "listed" if ok else "refused")
            if not ok:
                continue
            out.append({"id": mid, "sender": sender, "subject": _header(m, "Subject"), "date": _header(m, "Date"),
                        "snippet": m.get("snippet", ""), "received": int(m.get("internalDate", 0)) // 1000})
        return out

    def body(self, msg_id: str) -> str:
        """The plain-text body of a message this gate listed and allowed; '' otherwise."""
        listed = self._ok.get(msg_id)
        if not listed:
            self._audit(msg_id, "", "refused")
            return ""
        m = self._svc.users().messages().get(userId="me", id=msg_id, format="full").execute()
        sender = _header(m, "From")
        if not sender_allowed(sender, listed):
            self._audit(msg_id, sender, "refused")
            return ""
        self._audit(msg_id, sender, "read")
        return (_text_of(m.get("payload", {})) or m.get("snippet", ""))[:MAX_BODY]


def service_for(token_path=None):
    """A Gmail service on a read-only token, or None when there's no token."""
    try:
        from career_agent.integrations.gmail_otp import _build_service, available
        if token_path is None and not available():
            return None
        return _build_service(token_path)
    except Exception:                                      # noqa: BLE001 — no token or Google libraries
        return None
