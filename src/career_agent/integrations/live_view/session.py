"""RemoteSolveSession — assembles a remote-solve: mint token, start the CDP
screencast + live-view server, hand back a single-use link, then run the
MAIN-thread pump that (a) applies viewer taps to the page via sync Playwright
and (b) polls for the human's solve. `close()` tears it all down.

The pump lives here, on the main thread, because Playwright's sync API is
thread-affine — pointer events collected by the server thread must be applied
here, not there.
"""
from __future__ import annotations

import queue
import time

from .token import mint_token, build_url
from .server import LiveViewServer


class RemoteSolveSession:
    def __init__(self, page, host, port, ttl_s, allow_public, is_cleared,
                 clock=time.time, sleep=time.sleep, poll_interval_s=1.0):
        self.page = page
        self.host = host
        self.port = port
        self.ttl_s = ttl_s
        self.allow_public = allow_public
        self.is_cleared = is_cleared          # callable(page) -> bool
        self._clock = clock
        self._sleep = sleep
        self.poll_interval_s = poll_interval_s
        self._pointer_q = queue.Queue()
        self._cdp = None
        self._server = None

    def start(self) -> str:
        # Import the CDP bridge lazily so this module imports without Playwright.
        from career_agent.browser.live_view.cdp_bridge import start_screencast

        self._token = mint_token(self.ttl_s, self._clock())
        # Enforces private-by-default (raises on a public host without opt-in).
        url = build_url(self.host, self.port, self._token.value, self.allow_public)
        self._server = LiveViewServer(
            self.page, self._token, self.host, self.port, self._pointer_q)
        self._cdp = start_screencast(self.page, self._server.push_frame)
        self._server.start()
        return url

    def wait_until_cleared(self, timeout_s) -> bool:
        from career_agent.browser.live_view.cdp_bridge import forward_pointer

        vp = self.page.viewport_size or {"width": 900, "height": 1600}
        start = self._clock()
        while self._clock() - start < timeout_s:
            self._drain_pointers(forward_pointer, vp)
            if self.is_cleared(self.page):
                self._drain_pointers(forward_pointer, vp)   # apply any final taps
                return True
            self._sleep(self.poll_interval_s)
        return False

    def _drain_pointers(self, forward_pointer, vp) -> None:
        while True:
            try:
                nx, ny, kind = self._pointer_q.get_nowait()
            except queue.Empty:
                return
            try:
                forward_pointer(self._cdp, nx, ny, kind, vp["width"], vp["height"])
            except Exception:
                pass   # a bad tap must never crash the pump

    def close(self) -> None:
        from career_agent.browser.live_view.cdp_bridge import stop_screencast
        try:
            if self._cdp is not None:
                stop_screencast(self._cdp)
        finally:
            if self._server is not None:
                self._server.stop()
