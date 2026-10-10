"""The user's own LinkedIn profile as text, read through the agent's logged-in Chrome (never the user's own Chrome).

Used once in a while to fill gaps in the application profile (profile_intel.autofill): current title and employer,
education, certifications, languages. Read-only; it only opens the profile pages.
"""
from __future__ import annotations

from job_dashboard import agent_browser
from job_dashboard.sources.cdp.types import html_to_text

PAGES = ("", "details/experience/", "details/education/", "details/certifications/", "details/languages/")
MAX_CHARS = 6000


def read(cdp_url: str | None = None, session_factory=None) -> str:
    """The profile's text, '' when the agent Chrome isn't up or isn't logged in to LinkedIn."""
    from job_dashboard.sources.cdp.session import CdpSession
    url = cdp_url or agent_browser.cdp_url()
    if session_factory is None:
        if agent_browser.ensure_running(url):
            return ""
        session_factory = lambda: CdpSession(url, max_loads=len(PAGES), settle_ms=4000)  # noqa: E731
    parts = []
    try:
        with session_factory() as s:
            for page in PAGES:
                s.goto(f"https://www.linkedin.com/in/me/{page}")
                text = html_to_text(s.html())
                if "Sign in" in text[:400] and "Join now" in text[:800]:
                    return ""                                   # logged out
                parts.append(text[:MAX_CHARS])
    except Exception as e:                                      # noqa: BLE001 — a missing source is not an error
        print(f"[linkedin] own profile not read ({type(e).__name__}: {e})", flush=True)
    return "\n\n".join(p for p in parts if p)
