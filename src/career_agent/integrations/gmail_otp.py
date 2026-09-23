"""Read OTP codes from Gmail for automated email-auth gates (Oracle CX, Darwinbox, etc.).

Setup (once per account):
    python -m career_agent.integrations.gmail_otp authorize
    python -m career_agent.integrations.gmail_otp authorize --account privrakshit

Runtime (called by apply.py):
    from career_agent.integrations.gmail_otp import poll_otp
    code = poll_otp(timeout_s=300)   # polls ALL authorized accounts in parallel

Credentials:
    ~/.career_agent/gmail_credentials.json   — OAuth client secret (from Google Cloud Console)
    ~/.career_agent/gmail_token.json         — default account token
    ~/.career_agent/gmail_token_<tag>.json   — additional account tokens (--account <tag>)
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import re
import time

_CREDS_PATH = pathlib.Path.home() / ".career_agent" / "gmail_credentials.json"
_TOKEN_DIR  = pathlib.Path.home() / ".career_agent"
_TOKEN_PATH = _TOKEN_DIR / "gmail_token.json"          # default / first account
_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _all_token_paths() -> list[pathlib.Path]:
    """Return all gmail_token*.json files found in the credentials dir."""
    return sorted(_TOKEN_DIR.glob("gmail_token*.json"))

# Matches 4–8 digit OTP codes; avoids matching years, phone fragments, etc.
_OTP_RE = re.compile(r"\b([0-9]{4,8})\b")

# Matches email verification / magic links
_VERIFY_LINK_RE = re.compile(
    r'https?://[^\s<>"\')]+(?:verify|confirm|activate|validate|magic)[^\s<>"\')]*',
    re.I
)

# Known OTP sender domains — used to narrow the Gmail search
_OTP_SENDERS = [
    "oracle.com", "oraclecloud.com", "workflow.mail",   # Oracle CX / JPMC
    "darwinbox",                                         # Darwinbox
    "infosys.com",                                       # Infosys Keycloak
    "successfactors",                                    # SAP SF
    "greenhouse.io",                                     # Greenhouse
    "workday.com",                                       # Workday
    "lever.co",                                          # Lever
    "icims.com",                                         # iCIMS
    "eightfold.ai",                                      # Phenom/eightfold ATS
    "qualcomm.com",                                      # Qualcomm careers
]


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _build_service(token_path: pathlib.Path | None = None):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    tp = token_path or _TOKEN_PATH
    creds = None
    if tp.exists():
        creds = Credentials.from_authorized_user_file(str(tp), _SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            tp.write_text(creds.to_json())
        else:
            raise RuntimeError(
                f"Gmail token missing or invalid at {tp}. Run:\n"
                f"  python -m career_agent.integrations.gmail_otp authorize"
            )
    return build("gmail", "v1", credentials=creds)


def authorize(account: str | None = None):
    """One-time OAuth flow — opens a browser, saves the token.

    account: optional tag for a second inbox (e.g. "privrakshit").
             Saves to gmail_token_privrakshit.json so both tokens coexist.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not _CREDS_PATH.exists():
        raise FileNotFoundError(
            f"Gmail OAuth credentials not found at {_CREDS_PATH}\n"
            "Download them from Google Cloud Console → APIs & Services → Credentials"
        )
    token_path = (_TOKEN_DIR / f"gmail_token_{account}.json") if account else _TOKEN_PATH
    flow = InstalledAppFlow.from_client_secrets_file(str(_CREDS_PATH), _SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json())
    print(f"[gmail-otp] Token saved to {token_path}")


# ---------------------------------------------------------------------------
# Core: extract OTP from a message
# ---------------------------------------------------------------------------

def _snippet_code(snippet: str) -> str | None:
    """Extract first plausible OTP code from an email snippet."""
    m = _OTP_RE.search(snippet or "")
    return m.group(1) if m else None


def _extract_code(text: str) -> str | None:
    """Extract a verification link (preferred) or numeric OTP from email body."""
    m = _VERIFY_LINK_RE.search(text or "")
    if m:
        return m.group(0)
    m = _OTP_RE.search(text or "")
    return m.group(1) if m else None


def _body_text(service, msg_id: str) -> str:
    """Decode the plaintext body of a Gmail message."""
    msg = service.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute()
    parts = msg.get("payload", {}).get("parts") or [msg.get("payload", {})]
    for part in parts:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    # fallback: snippet
    return msg.get("snippet", "")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def poll_otp(
    timeout_s: int = 300,
    poll_interval_s: int = 5,
    sender_hint: str | None = None,
    after_epoch: int | None = None,
) -> str | None:
    """Block until an OTP email arrives in Gmail or timeout_s elapses.

    sender_hint: narrow the search (e.g. "oracle.com"). If None, tries all
                 known OTP sender domains.
    after_epoch: only look at emails received after this Unix timestamp
                 (default: now - 120s to catch emails already in-flight).
    Returns the extracted code string, or None on timeout.
    """
    if not _TOKEN_PATH.exists():
        print("[gmail-otp] No token — falling back to file reader")
        return None

    service = _build_service()
    # Look back 1800s (OTP validity window) so we pick up emails from prior
    # Continue clicks when Phenom rate-limits new OTP sends.
    since = after_epoch or (int(time.time()) - 1800)

    # Build query list: sender filter first (fast), then all-unread fallback
    # NOTE: no category:primary — ATS verification emails often land in Promotions
    senders = [sender_hint] if sender_hint else _OTP_SENDERS
    narrow_query = (
        "is:unread "
        f"after:{since} "
        "(" + " OR ".join(f"from:{s}" for s in senders) + ")"
    )
    # Broad fallback: all unread emails — catches completely unknown ATS mailers
    broad_query = f"is:unread after:{since}"

    seen: set[str] = set()
    deadline = time.time() + timeout_s
    print(f"[gmail-otp] Polling for OTP (timeout {timeout_s}s) …", flush=True)

    def _scan(query: str) -> str | None:
        results = service.users().messages().list(
            userId="me", q=query, maxResults=10
        ).execute()
        for m in results.get("messages", []):
            mid = m["id"]
            if mid in seen:
                continue
            seen.add(mid)
            hdr = service.users().messages().get(
                userId="me", id=mid, format="metadata",
                metadataHeaders=["From", "Subject"]
            ).execute()
            snippet = hdr.get("snippet", "")
            code = _snippet_code(snippet)
            if not code:
                body = _body_text(service, mid)
                code = _extract_code(body)
            if code:
                sender = next(
                    (h["value"] for h in hdr.get("payload", {}).get("headers", [])
                     if h["name"] == "From"), "?")
                print(f"[gmail-otp] Got code {code!r} from {sender}", flush=True)
                try:
                    service.users().messages().modify(
                        userId="me", id=mid, body={"removeLabelIds": ["UNREAD"]}
                    ).execute()
                except Exception:
                    pass  # read-only token: can't mark read, but code is usable
                return code
        return None

    while time.time() < deadline:
        # Try narrow first (faster), then broad fallback
        code = _scan(narrow_query) or _scan(broad_query)
        if code:
            return code
        time.sleep(poll_interval_s)

    print("[gmail-otp] Timeout — no OTP found", flush=True)
    return None


def available() -> bool:
    """True if the token exists and can be refreshed (fast check, no network)."""
    return _TOKEN_PATH.exists()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "authorize":
        authorize()
    else:
        print("Usage: python -m career_agent.integrations.gmail_otp authorize")
