"""One thread that owns Playwright for agent-driven apply runs.

Sync Playwright objects belong to the thread that made them, and FastAPI runs handlers on a pool, so every browser
step is a closure handed to this thread (`call`). It attaches over CDP to the one agent Chrome
(`agent_browser.ensure_running`), never the user's own Chrome. Tests pass `InlineActor`, which runs closures on the
caller's thread with a fake browser context."""
from __future__ import annotations

import queue
import threading
from concurrent.futures import Future

STEP_TIMEOUT_S = 240          # one tool step: a slow page, a résumé upload, a submit waiting for its confirmation


class BrowserActor:
    def __init__(self, connect=None):
        self._connect = connect or _connect_agent_chrome
        self._jobs: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._context = None
        self._lock = threading.Lock()

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="apply-browser", daemon=True)
                self._thread.start()

    def _loop(self) -> None:
        from career_agent.browser.page_prep import LEAVE_DIALOGS
        LEAVE_DIALOGS.set(True)                       # dialogs on this thread are the agent's to answer
        while True:
            fn, fut = self._jobs.get()
            if fut.set_running_or_notify_cancel():
                try:
                    fut.set_result(fn(self._browser_context()))
                except BaseException as e:            # noqa: BLE001 — handed to the caller
                    fut.set_exception(e)

    def _browser_context(self):
        """The agent Chrome's context, connected on first use and again after the browser went away."""
        ctx = self._context
        try:
            if ctx is not None:
                ctx.pages                              # raises once the CDP connection is gone
                return ctx
        except Exception:
            pass
        self._context = self._connect()
        return self._context

    def call(self, fn, timeout: float = STEP_TIMEOUT_S):
        """Run fn(browser_context) on the browser thread; its result, or its exception re-raised here."""
        self._ensure_thread()
        fut: Future = Future()
        self._jobs.put((fn, fut))
        return fut.result(timeout=timeout)


class InlineActor:
    """Same interface, no thread: runs fn(context) where it is called. For tests."""

    def __init__(self, context):
        self.context = context

    def call(self, fn, timeout: float = STEP_TIMEOUT_S):
        return fn(self.context)


def _connect_agent_chrome():
    from playwright.sync_api import sync_playwright
    from job_dashboard import agent_browser
    url = agent_browser.cdp_url()
    agent_browser.ensure_running(url)
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(url)
    return browser.contexts[0] if browser.contexts else browser.new_context()
