"""Gmail security-email watcher.

Checks whether a job site has sent a lockout/security email in the recent
past.  Called at the start of classify_node — if a match is found, the run
stops immediately and the domain gets a "blocked" cooldown in portal_state.

Always returns False on any Gmail error so a missing token or API hiccup
never blocks a real application.
"""
from __future__ import annotations

import time

# Subject / body phrases that indicate the site is suspicious of us.
_SECURITY_PHRASES = (
    "unusual activity",
    "unusual sign-in",
    "unusual login",
    "account locked",
    "account suspended",
    "account disabled",
    "suspicious activity",
    "suspicious login",
    "security alert",
    "account security",
    "unauthorized access",
    "we noticed",
)


def check_security_email(domain: str, lookback_minutes: int = 120) -> bool:
    """Return True if Gmail has a security/lockout email from *domain* in the
    last *lookback_minutes*.  False on any error or missing token.

    Uses the same Gmail service as gmail_otp so no separate auth is needed.
    """
    try:
        from .gmail_otp import _build_service, available
        if not available():
            return False

        from ..reliability.rate_limiter import domain_key
        d = domain_key(f"https://{domain}/")  # normalise: strip jobs./careers./etc.

        service = _build_service()
        since = int(time.time()) - lookback_minutes * 60
        phrase_q = " OR ".join(f'"{p}"' for p in _SECURITY_PHRASES)
        query = f"from:{d} after:{since} ({phrase_q})"

        result = service.users().messages().list(
            userId="me", q=query, maxResults=3
        ).execute()

        found = bool(result.get("messages"))
        if found:
            print(f"[inbox-watch] security email from {d!r} — stopping run", flush=True)
        return found
    except Exception as exc:
        print(f"[inbox-watch] check skipped ({type(exc).__name__}), proceeding", flush=True)
        return False
