"""The only module that touches Playwright. One own tab per run, no click / type / form API:
an adapter can navigate and listen to the responses the page itself makes, nothing else."""
from __future__ import annotations

import gzip
import json
import random
import re
import time
import urllib.request
from urllib.parse import urljoin, urlparse

from .types import Blocked, CapReached

BAD_URL = re.compile(r"authwall|/login|/checkpoint|/uas/|challenge|captcha", re.I)
BAD_TEXT = re.compile(
    r"unusual activity|verify you.re a human|security verification|"
    r"let.s do a quick security check|temporarily restricted", re.I)

_FETCH_JS = ("async ([u, m, h, b]) => { const r = await fetch(u, {method: m, credentials: 'include', redirect: 'manual', "
             "headers: h || {}, body: b}); return [r.status, await r.text()]; }")


def cdp_reachable(cdp_url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=timeout):
            return True
    except Exception:
        return False


def _playwright_connect(cdp_url: str):
    """(page, closer). closer detaches Playwright; it does not close Chrome or other tabs."""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(cdp_url)
        page = browser.contexts[0].new_page()
    except Exception:
        pw.stop()
        raise

    def closer():
        try:
            browser.close()
        finally:
            pw.stop()
    return page, closer


class Capture:
    """Collects the page's own responses whose URL contains any needle."""

    def __init__(self, page, needles):
        self._page, self._needles, self.responses = page, needles, []

    def _on(self, response):
        if any(n in response.url for n in self._needles):
            self.responses.append(response)

    def __enter__(self):
        self._page.on("response", self._on)
        return self

    def __exit__(self, *exc):
        self._page.remove_listener("response", self._on)

    def bodies(self):
        """(url, parsed json) for each captured response that parses."""
        for r in self.responses:
            try:
                yield r.url, r.json()
            except Exception:
                continue

    def exchanges(self):
        """(request headers, request body parsed, response json or None if it does not parse) per captured exchange."""
        for r in self.responses:
            try:
                rq = r.request
                raw = rq.post_data_buffer
                if raw and raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = raw.decode("utf-8", "replace") if raw else None
                try:
                    resp = r.json()
                except Exception:
                    resp = None
                yield dict(rq.all_headers()), body, resp
            except Exception:
                continue


class CdpSession:
    def __init__(self, cdp_url, *, max_loads, nap=None, connect=None, settle_ms=7000):
        self.cdp_url, self.max_loads, self.loads = cdp_url, max_loads, 0
        self._nap = nap or (lambda: time.sleep(random.uniform(6, 12)))
        self._connect = connect or _playwright_connect
        self._settle_ms = settle_ms
        self._page = self._closer = None

    def __enter__(self):
        self._page, self._closer = self._connect(self.cdp_url)
        return self

    def __exit__(self, *exc):
        for fn in (lambda: self._page.close(), lambda: self._closer()):
            try:
                fn()
            except Exception:
                pass

    def capture(self, *needles) -> Capture:
        return Capture(self._page, needles)

    def goto(self, url: str) -> None:
        if self.loads >= self.max_loads:
            raise CapReached(f"{self.max_loads} page loads")
        if self.loads:
            self._nap()
        self.loads += 1
        resp = self._page.goto(url, wait_until="domcontentloaded")
        self._check(getattr(resp, "status", None))
        self._page.wait_for_timeout(self._settle_ms)
        self._check(None)

    def fetch(self, url, *, hosts, method="GET", headers=None, body=None) -> str:
        """Same-origin fetch inside our own tab. Host-allowlisted; counts toward the cap; any non-200 is a block."""
        absolute = urljoin(self._page.url or "", url)
        host = urlparse(absolute).hostname or ""
        if not any(host == h or host.endswith("." + h) for h in hosts):
            raise ValueError(f"host {host!r} not allowed")
        if self.loads >= self.max_loads:
            raise CapReached(f"{self.max_loads} page loads")
        if self.loads:
            self._nap()
        self.loads += 1
        status, text = self._page.evaluate(_FETCH_JS, [absolute, method, headers or {}, body])
        if status != 200:
            raise Blocked(f"HTTP {status} on {host}")
        return text

    def _check(self, status):
        if status in (401, 403, 429) or BAD_URL.search(self._page.url or ""):
            raise Blocked(f"{self._page.url} status={status}")
        text = self._page.evaluate("document.body ? document.body.innerText.slice(0, 3000) : ''")
        if BAD_TEXT.search(text or ""):
            raise Blocked("challenge text on page")
