"""One rule for every click the agent makes: click once, wait for what it did, never click again because it was slow.

Clicking in a burst is how a form step gets skipped (the second "Continue" lands on the next page) and how the wrong tab
gets adopted. So: a minimum gap between any two clicks on a page (`pace`), and after a click that may navigate or
re-render, wait until the page actually changes and then goes quiet (`settle_after_click`)."""
from __future__ import annotations

import time

MIN_GAP_MS = 600
TIMING_SCALE = 1.0      # every wait and timeout below is multiplied by this; tests shrink it, production keeps 1.0


def ms(n: int) -> int:
    """A wait of `n` ms under TIMING_SCALE."""
    return max(0, int(n * TIMING_SCALE))


def timeout_ms(n: int) -> int:
    """A Playwright timeout of `n` ms under TIMING_SCALE, never below 1s (0 would mean no timeout at all)."""
    return max(min(n, 1000), ms(n))


def wait(page, n: int) -> None:
    page.wait_for_timeout(ms(n))


def pace(page, min_gap_ms: int = MIN_GAP_MS) -> None:
    """Wait out the rest of the minimum gap since this page's last click, then stamp the new one."""
    try:
        last = getattr(page, "_agent_last_click", 0.0)
        gap = ms(min_gap_ms) / 1000 - (time.monotonic() - last)
        if gap > 0:
            page.wait_for_timeout(int(gap * 1000))
        page._agent_last_click = time.monotonic()
    except Exception:
        pass


def page_signature(page):
    try:
        return (page.url, hash(page.inner_text("body")[:6000]))
    except Exception:
        return (getattr(page, "url", ""), 0)


def _text_hash(page):
    try:
        return hash(page.inner_text("body")[:6000])
    except Exception:
        return 0


def wait_until_stable(page, quiet_polls: int = 5, poll_ms: int = 300, max_ms: int = 12000) -> None:
    """Wait until the page text has stopped changing for `quiet_polls` polls in a row (a step that is still drawing,
    a spinner, a slide transition). Reading or screenshotting before this reads the page that is going away."""
    last, same, waited = None, 0, 0
    while waited < max_ms:
        cur = _text_hash(page)
        same = same + 1 if cur == last else 0
        if same >= quiet_polls:
            return
        last = cur
        wait(page, poll_ms)
        waited += poll_ms


def settle_after_click(page, before, max_wait_ms: int = 25000, quiet_ms: int = 2500) -> None:
    """Wait for what the click started, then for the NEW page to finish drawing. A single-page app changes the URL
    first and the content later, so "the URL changed" is not "the next step is on screen": the page text must change
    (or a changed URL must have stayed put for a while) and then stop changing."""
    before_url, before_text = before[0], before[1]
    waited, changed = 0, False
    while waited < max_wait_ms and not changed:
        wait(page, 300)
        waited += 300
        url, text = page_signature(page)
        changed = text != before_text or (url != before_url and waited >= 6000)
    if changed:
        wait_until_stable(page)
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms(8000))
    except Exception:
        pass
    wait(page, quiet_ms)


def click_and_settle(page, do_click, *, max_wait_ms: int = 25000) -> None:
    """Pace, click exactly once (`do_click()` raises if the click itself failed), then wait for the page to respond."""
    pace(page)
    before = page_signature(page)
    do_click()
    try:
        settle_after_click(page, before, max_wait_ms)
    except Exception:
        pass                                  # the click went through; nothing here may trigger another one


def wait_for_change(page, before, max_wait_ms: int = 12000) -> bool:
    """After a click that showed no change yet: give the page more time to answer. True if it changed."""
    waited = 0
    while waited < max_wait_ms:
        wait(page, 500)
        waited += 500
        if page_signature(page) != before:
            wait_until_stable(page)
            return True
    return False
