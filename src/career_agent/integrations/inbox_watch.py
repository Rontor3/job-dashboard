"""Gmail security-email watcher.

Checks whether a job site has sent a lockout/security email in the recent
past.  Called at the start of classify_node — if a match is found, the run
stops immediately and the domain gets a "blocked" cooldown in portal_state.

Always returns False on any Gmail error so a missing token or API hiccup
never blocks a real application.
"""
from __future__ import annotations

import time

# Broad Gmail search terms — cast a wide net to find candidate emails.
_SEARCH_PHRASES = (
    "unusual activity",
    "unusual sign-in",
    "account locked",
    "account suspended",
    "account disabled",
    "suspicious activity",
    "suspicious login",
    "security alert",
    "unauthorized access",
)

# Hard lockout words that must appear in the snippet/body to confirm it's
# a real problem — not just a benign "you signed in from a new device" notice.
_LOCKOUT_WORDS = (
    "locked", "suspended", "disabled", "blocked", "restricted",
    "unusual", "suspicious", "unauthorized", "violated", "flagged",
    "review your account", "verify your identity", "unusual activity",
)

# Phrases that indicate a benign login notification — skip even if a
# search phrase matched.
_BENIGN_PHRASES = (
    "successfully signed in",
    "new sign-in to your account",
    "you signed in",
    "new device",
    "new location",
    "if this was you",
    "welcome back",
)


def _is_lockout(snippet: str) -> bool:
    """True if the email snippet reads as a lockout, not a benign login notice."""
    low = snippet.lower()
    if any(b in low for b in _BENIGN_PHRASES):
        return False
    return any(w in low for w in _LOCKOUT_WORDS)


def check_security_email(domain: str, lookback_minutes: int = 120) -> bool:
    """Return True if Gmail has a confirmed lockout email from *domain* in the
    last *lookback_minutes*.  False on any error or missing token.

    Two-stage: (1) broad Gmail search to find candidates, (2) snippet check
    to confirm it's a real lockout vs. a benign "new device" notification.
    Uses the same Gmail service as gmail_otp — no separate auth needed.
    """
    try:
        from .gmail_otp import _build_service, available
        if not available():
            return False

        from ..reliability.rate_limiter import domain_key
        d = domain_key(f"https://{domain}/")

        service = _build_service()
        since = int(time.time()) - lookback_minutes * 60
        phrase_q = " OR ".join(f'"{p}"' for p in _SEARCH_PHRASES)
        query = f"from:{d} after:{since} ({phrase_q})"

        result = service.users().messages().list(
            userId="me", q=query, maxResults=5
        ).execute()

        for msg in result.get("messages", []):
            meta = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["Subject"],
            ).execute()
            snippet = meta.get("snippet", "")
            subject = next(
                (h["value"] for h in meta.get("payload", {}).get("headers", [])
                 if h["name"] == "Subject"),
                "",
            )
            combined = f"{subject} {snippet}"
            if _is_lockout(combined):
                print(
                    f"[inbox-watch] lockout email from {d!r}: {subject!r} — stopping run",
                    flush=True,
                )
                return True

        return False
    except Exception as exc:
        print(f"[inbox-watch] check skipped ({type(exc).__name__}), proceeding", flush=True)
        return False
