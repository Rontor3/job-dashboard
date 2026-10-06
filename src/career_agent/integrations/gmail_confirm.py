"""Did the application go through? Look for the confirmation EMAIL.

A second proof of submission, next to the page check: boards and ATSes mail "your application was sent / thank you for
applying" within minutes. This catches a form submitted by hand after its tab was closed, or while the dashboard was off.

Narrow by design (the user's permission is for this and for sign-in codes, nothing else):
  * only runs when the dashboard setting `gmail_confirmation_check` is on (off by default; switch in the queue panel);
  * asks Gmail for METADATA only — subject, sender, date and Gmail's short snippet — never a message body;
  * the search is limited to "application sent/received" wording after the form was left open;
  * a match needs the job's company (or its title) in the subject/snippet/sender; nothing else is looked at or stored
    beyond the matched subject, sender and date."""
from __future__ import annotations

import re
import time
from email.utils import parsedate_to_datetime

from . import gmail_otp

_SUBJECT_OK = re.compile(
    r"application (was )?(sent|received|submitted)|application has been (received|submitted)"
    r"|thank you for (applying|your application)|we(?:'ve| have) received your application"
    r"|you(?:'ve| have)? applied\b|your application (to|for|with)\b", re.I)
_NOT_A_CONFIRMATION = re.compile(r"complete your application|finish your application|get started|reminder|still interested|"
                                 r"application (is )?incomplete|continue your application", re.I)
_COMPANY_NOISE = {"pvt", "ltd", "limited", "inc", "llc", "llp", "corp", "corporation", "co", "private", "plc", "gmbh",
                  "technologies", "technology", "labs", "lab", "solutions", "services", "group", "the", "and", "of"}
_GENERIC_NAMES = {"ai", "team", "tech", "data", "labs", "jobs", "careers", "hr", "it", "ml", "ai ml", "data science", "software"}
_TITLE_NOISE = {"the", "and", "of", "for", "a", "an", "to", "in", "senior", "junior", "lead", "sr", "jr"}


def _tokens(text: str, noise: set) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2 and t not in noise]


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))


def company_in(msg: dict, company: str) -> bool:
    """The company's name, as a WHOLE phrase, in the subject or the sender (name or domain). Never the snippet, and never
    a loose word: "A.Team" must not match an email that merely says "the team"."""
    words = [w for w in re.findall(r"[a-z0-9]+", (company or "").lower()) if w not in _COMPANY_NOISE]
    if not words:
        return False
    phrase = " ".join(words)
    if len(phrase) < 4 or phrase in _GENERIC_NAMES:
        return False                                           # a company called "AI" or "Team" cannot be told from any email
    subject, sender = _norm(msg.get("subject")), _norm(msg.get("from"))
    if re.search(r"\b" + re.escape(phrase) + r"\b", subject) or re.search(r"\b" + re.escape(phrase) + r"\b", sender):
        return True
    squashed = "".join(words)                                  # "thales" inside "jobalerts.thalesgroup.com"
    return len(squashed) >= 5 and squashed in (msg.get("from") or "").lower().replace(" ", "").replace("-", "")


def match_confirmation(msg: dict, company: str, title: str = "") -> bool:
    """Pure: is this email ({subject, from, snippet}) the application confirmation for this company / role?"""
    subject, sender, snippet = msg.get("subject") or "", msg.get("from") or "", msg.get("snippet") or ""
    if not _SUBJECT_OK.search(subject):
        return False                                # the wording must be in the SUBJECT, not a newsletter's snippet
    if _NOT_A_CONFIRMATION.search(subject):
        return False
    hay = f"{subject} {snippet} {sender}".lower()
    if company_in(msg, company):
        return True
    role = _tokens(title, _TITLE_NOISE)
    return len(role) >= 2 and sum(t in hay for t in role) >= max(2, len(role) - 1)


def _header(headers: list, name: str) -> str:
    return next((h["value"] for h in headers if h.get("name", "").lower() == name.lower()), "")


_QUERY = ("subject:(application OR applying OR applied) (sent OR received OR submitted OR \"thank you\" OR \"you applied\")")


def iter_confirmations(service, after_epoch: int, max_results: int = 100):
    """Recent confirmation-worded mail as {id, subject, from, snippet, date}. METADATA only: no message body is fetched."""
    res = service.users().messages().list(userId="me", q=f"after:{int(after_epoch)} ({_QUERY})", maxResults=max_results).execute()
    for m in res.get("messages", []):
        meta = service.users().messages().get(userId="me", id=m["id"], format="metadata",
                                              metadataHeaders=["Subject", "From", "Date"]).execute()
        hdr = meta.get("payload", {}).get("headers", [])
        try:
            when = parsedate_to_datetime(_header(hdr, "Date")).isoformat()
        except Exception:
            when = ""
        yield {"id": m["id"], "subject": _header(hdr, "Subject"), "from": _header(hdr, "From"),
               "snippet": meta.get("snippet", ""), "date": when}


def search_confirmation(service, company: str, title: str, after_epoch: int) -> dict | None:
    """The confirmation mail for this job, if one has arrived."""
    for msg in iter_confirmations(service, after_epoch, 30):
        if match_confirmation(msg, company, title):
            return {k: msg[k] for k in ("id", "subject", "from", "date")}
    return None


def list_confirmations(after_epoch: int, max_results: int = 100) -> list[dict]:
    """Confirmation mail across the authorised inboxes (a miss or an unreachable Gmail gives [])."""
    out = []
    for tp in gmail_otp._all_token_paths():
        try:
            out += [m for m in iter_confirmations(gmail_otp._build_service(tp), after_epoch, max_results)
                    if _SUBJECT_OK.search(m["subject"]) and not _NOT_A_CONFIRMATION.search(m["subject"])]
        except Exception as e:
            print(f"[gmail-confirm] {tp.name}: skipped ({type(e).__name__})", flush=True)
    return out


def find_confirmation(company: str, title: str, after_epoch: int | None = None):
    """Across the authorised inboxes. None if not found or Gmail is unreachable (a miss, never an error)."""
    since = after_epoch or int(time.time()) - 3 * 86400
    for tp in gmail_otp._all_token_paths():
        try:
            hit = search_confirmation(gmail_otp._build_service(tp), company, title, since)
        except Exception as e:
            print(f"[gmail-confirm] {tp.name}: skipped ({type(e).__name__})", flush=True)
            continue
        if hit:
            return hit
    return None
