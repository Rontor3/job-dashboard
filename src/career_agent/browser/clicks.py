"""One rule for every click the agent makes: click once, wait for what it did, never click again because it was slow.

Clicking in a burst is how a form step gets skipped (the second "Continue" lands on the next page) and how the wrong tab
gets adopted. So: a minimum gap between any two clicks on a page (`pace`), and after a click that may navigate or
re-render, wait until the page actually changes and then goes quiet (`settle_after_click`). `act` wraps the whole
Action-Confirm step and returns an `Observation` (the page to continue on + what happened while it loaded), so the next
decision is made on a stable page and knows about the dialog, tab or modal the click produced.

"Quiet" is read from a watcher injected into the page and its application frames: no DOM mutation for QUIET_MS, no
fetch/XHR in flight, nothing visible marked busy. Where the watcher can't run, the body-text hash is the fallback."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

MIN_GAP_MS = 600
QUIET_MS = 500          # no DOM mutation for this long = done drawing
NET_GRACE_MS = 3000     # a request still open after the DOM has been quiet this long is a long-poll/beacon: ignore it
POLL_MS = 150

# Idempotent. Counts mutations that change what is on screen or what is clickable; class/style churn (carousels,
# hover effects) is left out so an animated banner can't keep a page "busy" forever.
_WATCH_JS = """() => {
  if (window.__agentQ) return true;
  const q = window.__agentQ = {last: performance.now(), pending: 0, n: 0};
  const bump = () => { q.last = performance.now(); q.n++; };
  new MutationObserver(bump).observe(document.documentElement, {subtree: true, childList: true, characterData: true,
    attributes: true, attributeFilter: ['disabled', 'hidden', 'aria-hidden', 'aria-busy', 'aria-expanded', 'open', 'value']});
  const f = window.fetch;
  if (f) window.fetch = function (...a) { q.pending++; return f.apply(this, a).finally(() => { q.pending--; bump(); }); };
  const send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (...a) {
    q.pending++; this.addEventListener('loadend', () => { q.pending--; bump(); }, {once: true}); return send.apply(this, a); };
  return true;
}"""
_STATE_JS = """() => {
  const q = window.__agentQ; if (!q) return null;
  const busy = [...document.querySelectorAll('[aria-busy=true],[role=progressbar],.spinner,.loading,.loader')]
    .some(e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden');
  // visible controls: a form/menu revealed by a class or style flip (not counted as a mutation) still shows up here
  const vis = [...document.querySelectorAll('input:not([type=hidden]),select,textarea,button,[role=button],[role=menuitem],'
    + '[role=option],[role=combobox],[role=radio],[role=checkbox]')].filter(e => e.getClientRects().length > 0).length;
  return {idle: performance.now() - q.last, pending: Math.max(q.pending, 0), busy, n: q.n, vis, ready: document.readyState};
}"""
_MODAL_JS = """() => {
  for (const d of document.querySelectorAll('[role=dialog],[role=alertdialog],dialog[open],[aria-modal=true]')) {
    if (d.getClientRects().length === 0) continue;
    const r = d.getBoundingClientRect(); if (r.width < 50 || r.height < 50) continue;
    const name = d.getAttribute('aria-label') || (d.querySelector('h1,h2,h3,[role=heading]') || d).innerText || '';
    return name.trim().split('\\n')[0].slice(0, 80) || 'modal';
  }
  return null;
}"""


def pace(page, min_gap_ms: int = MIN_GAP_MS) -> None:
    """Wait out the rest of the minimum gap since this page's last click, then stamp the new one."""
    try:
        last = getattr(page, "_agent_last_click", 0.0)
        wait = min_gap_ms / 1000 - (time.monotonic() - last)
        if wait > 0:
            page.wait_for_timeout(int(wait * 1000))
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


def _watched_frames(page) -> list:
    """The main frame + every frame that could be the application (captcha/ads/chat frames never settle and never
    matter). Installs the watcher where it is missing — a frame that just navigated starts fresh, idle=0."""
    from .perception import is_denied_frame
    out = []
    for fr in page.frames:
        if fr is not page.main_frame and is_denied_frame(fr.url):
            continue
        try:
            fr.evaluate(_WATCH_JS)
            out.append(fr)
        except Exception:
            pass                               # detached mid-navigation / CSP: that frame falls back to the text hash
    return out


def dom_states(page) -> list | None:
    """Watcher readings for the page's frames, or None where the watcher can't run at all (fallback to text hash)."""
    try:
        frames = _watched_frames(page)
    except Exception:
        return None
    states = []
    for fr in frames:
        try:
            s = fr.evaluate(_STATE_JS)
        except Exception:
            continue
        if s:
            states.append(s)
    return states or None


def is_quiet(states: list) -> bool:
    return all(s["ready"] != "loading" and not s["busy"] and s["idle"] >= QUIET_MS
               and (s["pending"] == 0 or s["idle"] >= NET_GRACE_MS) for s in states)


def _mutations(states) -> tuple:
    """What a click can change: watched mutations, and how many controls are visible."""
    return (sum(s["n"] for s in states or []), sum(s.get("vis", 0) for s in states or []))


def _text_stable(page, quiet_polls: int, poll_ms: int, max_ms: int) -> bool:
    last, same, waited = None, 0, 0
    while waited < max_ms:
        cur = _text_hash(page)
        same = same + 1 if cur == last else 0
        if same >= quiet_polls:
            return True
        last = cur
        page.wait_for_timeout(poll_ms)
        waited += poll_ms
    return False


def wait_until_stable(page, quiet_polls: int = 5, poll_ms: int = 300, max_ms: int = 12000) -> bool:
    """Wait until the page is done drawing (a step that is still rendering, a spinner, a slide transition, a request
    whose answer will redraw the form). Reading or screenshotting before this reads the page that is going away.
    True if it went quiet, False if `max_ms` ran out first."""
    waited = 0
    while waited < max_ms:
        states = dom_states(page)
        if states is None:
            return _text_stable(page, quiet_polls, poll_ms, max_ms - waited)
        if is_quiet(states):
            return True
        page.wait_for_timeout(POLL_MS)
        waited += POLL_MS
    return False


def settle_after_click(page, before, max_wait_ms: int = 25000, quiet_ms: int = 300, mutations_before=None,
                       elsewhere=None):
    """Wait for what the click started, then for the NEW page to finish drawing. A single-page app changes the URL
    first and the content later, so "the URL changed" is not "the next step is on screen": the page text (or the
    watched DOM) must change — or a changed URL must have stayed put for a while — and then stop changing.
    `elsewhere()` True = the click's result is not on this page (it opened a tab): stop waiting here.
    Returns (changed, stable)."""
    before_url, before_text = before[0], before[1]
    waited, changed = 0, False
    while waited < max_wait_ms and not changed:
        page.wait_for_timeout(300)
        waited += 300
        if elsewhere is not None and elsewhere():
            return True, False
        url, text = page_signature(page)
        changed = text != before_text or (url != before_url and waited >= 6000)
        if not changed and mutations_before is not None:
            states = dom_states(page)
            # same document, DOM changed (a button enabled, an inline error, a section revealed) and already quiet
            changed = bool(states) and url == before_url and _mutations(states) != mutations_before and is_quiet(states)
    stable = wait_until_stable(page) if changed else False
    if quiet_ms:
        page.wait_for_timeout(quiet_ms)
    return changed, stable


@dataclass
class Observation:
    page: object                        # the page to continue on (a new tab the click opened, else the same page)
    changed: bool
    stable: bool
    url: str = ""
    modal: str | None = None
    intercepts: list = field(default_factory=list)   # "dialog confirm dismissed: …", "new tab: host", "modal: …"


def _host(url) -> str:
    return urlparse(url or "").netloc


def visible_modal(page) -> str | None:
    try:
        return page.evaluate(_MODAL_JS)
    except Exception:
        return None


def act(page, do_click, *, max_wait_ms: int = 25000) -> Observation:
    """The Action-Confirm step. Pace, click exactly once (`do_click()` raises if the click itself failed — then nothing
    happened and the caller may try another control), wait for the page to respond and go quiet, then report what the
    click produced. Nothing after the click can trigger a second one."""
    pace(page)
    log: list[str] = []
    ctx = getattr(page, "context", None)
    try:
        tabs_before = list(ctx.pages)
    except Exception:
        tabs_before = None

    def on_dialog(d):                   # alert/confirm/prompt: dismiss (Playwright's default) but say so;
        try:                            # a "leave page?" prompt is our own navigation asking — let it go
            log.append(f"dialog {d.type} {'accepted' if d.type == 'beforeunload' else 'dismissed'}: {d.message[:80]}")
            d.accept() if d.type == "beforeunload" else d.dismiss()
        except Exception:
            pass

    try:
        page.on("dialog", on_dialog)
    except Exception:
        pass
    before = page_signature(page)
    states = dom_states(page)
    try:
        do_click()
        changed, stable = False, False
        try:
            changed, stable = settle_after_click(page, before, max_wait_ms,
                                                 mutations_before=_mutations(states) if states else None,
                                                 elsewhere=(lambda: len(ctx.pages) > len(tabs_before)
                                                            or page.is_closed()) if tabs_before is not None else None)
        except Exception:
            pass                        # the click went through; nothing here may trigger another one
    finally:
        try:
            page.remove_listener("dialog", on_dialog)
        except Exception:
            pass
    active = page
    try:
        fresh = [p for p in ctx.pages if p not in tabs_before and not p.is_closed()] if tabs_before is not None else []
        if fresh:
            active = fresh[-1]
            log.append(f"new tab: {_host(active.url) or active.url}")
            stable = wait_until_stable(active)
            changed = True
        elif page.is_closed():          # the click closed this tab (OAuth pop-up done): continue on the newest one
            active = ctx.pages[-1]
            log.append("tab closed by click")
    except Exception:
        pass
    url = getattr(active, "url", "")
    if _host(url) and _host(before[0]) and _host(url) != _host(before[0]):
        log.append(f"host: {_host(before[0])} -> {_host(url)}")
    modal = visible_modal(active)
    if modal:
        log.append(f"modal: {modal}")
    return Observation(active, changed, stable, url, modal, log)


def click_and_settle(page, do_click, *, max_wait_ms: int = 25000) -> None:
    """Pace, click exactly once (`do_click()` raises if the click itself failed), then wait for the page to respond."""
    act(page, do_click, max_wait_ms=max_wait_ms)


def wait_for_change(page, before, max_wait_ms: int = 12000) -> bool:
    """After a click that showed no change yet: give the page more time to answer. True if it changed."""
    waited = 0
    while waited < max_wait_ms:
        page.wait_for_timeout(500)
        waited += 500
        if page_signature(page) != before:
            wait_until_stable(page)
            return True
    return False
