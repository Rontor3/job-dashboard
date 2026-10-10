"""Persistent-context Chrome launcher. A real on-disk profile so sessions and
cookies persist across runs, headed by default.

CDP mode: pass cdp_url to attach to the agent's isolated Chrome
(job_dashboard.agent_browser), launching it on demand — never the user's own
Chrome. close() disconnects cleanly without killing that browser.
"""
from __future__ import annotations

from pathlib import Path


def launch(settings, cdp_url: str | None = None):
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    if cdp_url:
        from job_dashboard.agent_browser import ensure_running
        problem = ensure_running(cdp_url)
        if problem:
            pw.stop()
            raise RuntimeError(problem)
        try:
            browser = pw.chromium.connect_over_cdp(cdp_url, timeout=60000)
        except Exception as e:
            pw.stop()
            # attaching waits for EVERY tab to answer; one frozen tab ("Page unresponsive") blocks it for good
            why = str(e).splitlines()[0] if str(e) else type(e).__name__
            hint = (" — a tab is probably frozen; close it (Chrome's task manager, Shift+Esc, shows which)"
                    if "Timeout" in type(e).__name__ or "Timeout" in why else "")
            raise RuntimeError(f"could not attach to the agent browser: {why}{hint}") from e
        if browser.contexts:
            context = browser.contexts[0]
        else:
            print("[browser] CDP: no existing contexts, creating one", flush=True)
            context = browser.new_context()
        page = context.new_page()
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
