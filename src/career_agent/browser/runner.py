"""Persistent-context Chrome launcher. A real on-disk profile so sessions and
cookies persist across runs, headed by default.

CDP mode: pass cdp_url (e.g. "http://localhost:9222") to attach to an
already-running Chrome instead of launching a new one.  close() disconnects
cleanly without killing the user's browser.
"""
from __future__ import annotations

from pathlib import Path


def wake_tabs(cdp_url: str) -> int:
    """Bring every tab to the front once, over Chrome's HTTP endpoint (no websocket, so a frozen tab can't block it).
    Chrome freezes background tabs after a while; a frozen tab never answers, and attaching waits for every tab
    (live 2026-10-17: 4 sleeping tabs failed 19 queued applications). Returns how many tabs were woken."""
    import json
    import urllib.request
    base = cdp_url.rstrip("/")
    tabs = [t for t in json.load(urllib.request.urlopen(f"{base}/json", timeout=10)) if t.get("type") == "page"]
    for t in tabs:
        try:
            urllib.request.urlopen(f"{base}/json/activate/{t['id']}", timeout=5).read()
        except Exception:
            pass
    return len(tabs)


def background_page(context, browser=None):
    """A new tab that opens BEHIND the user's current one: Playwright's new_page() brings the Chrome window to the
    front on every run (live 2026-10-19: "my current tab keeps shifting to chrome"). Falls back to new_page()."""
    if browser is not None:
        try:
            cdp = browser.new_browser_cdp_session()
            with context.expect_page(timeout=10000) as info:
                cdp.send("Target.createTarget", {"url": "about:blank", "background": True})
            page = info.value
            try:                    # the page still believes it has focus: focus-gated widgets keep working
                page.context.new_cdp_session(page).send("Emulation.setFocusEmulationEnabled", {"enabled": True})
            except Exception:
                pass
            return page
        except Exception:
            pass
    return context.new_page()


def _attach(pw, cdp_url: str, timeout_ms: int):
    return pw.chromium.connect_over_cdp(cdp_url, timeout=timeout_ms)


def launch(settings, cdp_url: str | None = None):
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    if cdp_url:
        try:
            browser = _attach(pw, cdp_url, 30000)
        except Exception:
            try:                                          # a sleeping tab blocks attaching: wake them all, try again
                print(f"[browser] attach stalled; woke {wake_tabs(cdp_url)} tab(s), retrying", flush=True)
                browser = _attach(pw, cdp_url, 60000)
            except Exception as e:
                pw.stop()
                # attaching waits for EVERY tab to answer; one hung tab ("Page unresponsive") still blocks it
                raise RuntimeError("could not attach to Chrome even after waking every tab — a tab is hung; close it "
                                   f"(Chrome's task manager, Shift+Esc, shows which): {type(e).__name__}") from e
        if browser.contexts:
            context = browser.contexts[0]
        else:
            print("[browser] CDP: no existing contexts, creating one", flush=True)
            context = browser.new_context()
        page = background_page(context, browser)
        print(f"[browser] CDP connected → {cdp_url}", flush=True)
        return pw, context, page, browser
    Path(settings.user_data_dir).mkdir(parents=True, exist_ok=True)
    context = pw.chromium.launch_persistent_context(
        settings.user_data_dir, headless=not settings.headed,
    )
    page = context.pages[0] if context.pages else context.new_page()
    return pw, context, page, None


class TabLedger:
    """The tabs THIS run opened. A tab opened only to read something (a JD, a pop-up, a social link, a stale step) is
    closed once it has served; the tab the run ends on stays for the human. A tab the user already had open (reused
    for the job) or anything this run did not open is never touched."""

    def __init__(self, context, first_page=None, max_open: int = 2):
        self.opened, self.user, self.max_open = [], set(), max_open
        if first_page is not None:
            self.opened.append(first_page)
        try:
            context.on("page", lambda p: self.opened.append(p))
        except Exception:
            pass

    def mark_user_owned(self, page) -> None:
        self.user.add(id(page))

    def _mine(self, p) -> bool:
        return id(p) not in self.user

    def trim(self, keep) -> int:
        """While working: keep at most `max_open` of this run's tabs, `keep` (the current one) first."""
        live = [p for p in self.opened if self._mine(p) and not _closed(p)]
        n = 0
        for p in live[:-self.max_open] if len(live) > self.max_open else []:
            if p is not keep:
                n += _close(p)
        return n

    def close_all_but(self, keep=(), keep_urls=()) -> int:
        """End of run: close every tab this run opened except `keep` and any showing one of `keep_urls`."""
        keep = [k for k in keep if k is not None]
        n = 0
        for p in list(self.opened):
            if not self._mine(p) or _closed(p) or any(p is k for k in keep):
                continue
            if any(u and p.url and p.url.split("#")[0] == u.split("#")[0] for u in keep_urls):
                continue
            n += _close(p)
        return n


def tab_id_for(context, url: str):
    """Chrome's own id for the tab showing `url` (the id /json/list reports), so a later process can find that tab again
    even after it navigates (a submit lands on a confirmation URL). None if it cannot be read."""
    want = (url or "").split("#")[0]
    for pg in getattr(context, "pages", []):
        try:
            if pg.url.split("#")[0] == want:
                return context.new_cdp_session(pg).send("Target.getTargetInfo")["targetInfo"]["targetId"]
        except Exception:
            continue
    return None


def _closed(p) -> bool:
    try:
        return p.is_closed()
    except Exception:
        return True


def _close(p) -> int:
    try:
        p.close()
        return 1
    except Exception:
        return 0


def close(pw, context, page=None, cdp_browser=None) -> None:
    try:
        if cdp_browser is not None:
            try:
                if page is not None:
                    page.close()  # only close the tab we opened; leave Chrome alive
            except Exception:
                pass
            # ponytail: don't call cdp_browser.close() — it sends Browser.close over CDP
            # which corrupts Chrome's context-management state for subsequent reconnects
        else:
            context.close()
    finally:
        pw.stop()
