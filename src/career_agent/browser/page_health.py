"""Page health: recognise Chrome's own error shell and replay the intended URL once.

A re-run re-enters a job through history state; a stale POST makes the tab land on
chrome-error://chromewebdata ("ERR_CACHE_MISS"), which is not a page at all — the
engines read it as unreachable content and give up (job 29987 landed there right
after a Login click, and a fresh GET of the same URL worked live). Detection is a
URL check plus one cheap body evaluate, read the way boards/run.py:_blocked reads
text. Recovery is ONE fresh bar-style GET of the intended URL (address-bar
navigation is a GET), then the usual stability wait. One recovery per
(intended_url, error signature): a page that fails the same way again is dead,
never a replay loop."""
from __future__ import annotations

import re

_ERR_RE = re.compile(r"ERR_[A-Z_]{4,}")

# One fresh replay per (intended_url, error signature) for the run: the second
# sighting of the same pair is a dead page, not another goto.
_TRIED: set[tuple[str, str]] = set()

_BODY_JS = """() => document.body ? document.body.innerText.slice(0, 2000) : ''"""


def chrome_error(page) -> str | None:
    """The error signature when the tab is parked on a Chrome error page, else None:
    the URL itself (chrome-error://...) or an ERR_* code in the visible body text."""
    try:
        if (page.url or "").startswith("chrome-error://"):
            return "chrome-error"
    except Exception:
        return None
    try:
        body = page.evaluate(_BODY_JS) or ""
    except Exception:
        return None                              # unreadable body: nothing says the page is dead
    m = _ERR_RE.search(body)
    return m.group(0) if m else None


def recover(page, intended_url) -> str | None:
    """None when the page is healthy; "recovered" after one fresh GET of the
    intended URL landed on something readable; "dead" when the page fails the
    same way again (or the goto throws). The caller stops on "dead"."""
    sig = chrome_error(page)
    if not sig or not intended_url:
        return None
    key = (intended_url, sig)
    if key in _TRIED:
        return "dead"
    _TRIED.add(key)
    try:
        page.goto(intended_url, wait_until="domcontentloaded")
    except Exception:
        return "dead"
    from .clicks import wait_until_stable
    wait_until_stable(page)
    return "dead" if chrome_error(page) else "recovered"
