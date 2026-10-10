"""The agent's own browser: one Chrome process, its own profile under the data root, its own debug port.

Every browser consumer (job sources, hiring posts, the apply agent, the submit watcher) attaches here and nowhere
else, so the agent never touches your everyday Chrome, its tabs or its cookies. A Chrome started with its own
``--user-data-dir`` runs as a separate instance next to your normal Chrome, so launching it never disturbs yours.

Config: ``AGENT_CDP_PORT`` (default 9333), ``AGENT_CHROME_PATH`` (default Google Chrome, else Playwright Chromium),
or ``CAREER_AGENT_CDP_URL`` to point at a browser you manage yourself.
"""
from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from pathlib import Path

from job_dashboard import paths

_LOCAL_BROWSERS = paths.REPO_ROOT / ".playwright-browsers"
if _LOCAL_BROWSERS.is_dir():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_LOCAL_BROWSERS))

_MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def cdp_url() -> str:
    explicit = (os.getenv("CAREER_AGENT_CDP_URL") or "").strip()
    if explicit.startswith("http"):
        return explicit
    return f"http://127.0.0.1:{os.getenv('AGENT_CDP_PORT', '9333')}"


def reachable(url: str | None = None, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"{url or cdp_url()}/json/version", timeout=timeout):
            return True
    except Exception:
        return False


def _executable() -> str | None:
    explicit = os.getenv("AGENT_CHROME_PATH")
    if explicit:
        return explicit
    if Path(_MAC_CHROME).exists():
        return _MAC_CHROME
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            return pw.chromium.executable_path
    except Exception:
        return None


def launch_args(port: int) -> list[str]:
    return [f"--remote-debugging-port={port}", f"--user-data-dir={paths.BROWSER_PROFILE}",
            "--no-first-run", "--no-default-browser-check", "--remote-allow-origins=*"]


def _page_count(url: str) -> int:
    import json
    with urllib.request.urlopen(f"{url}/json/list", timeout=3) as r:
        return sum(1 for t in json.load(r) if t.get("type") == "page")


def ensure_window(url: str) -> None:
    """On macOS Chrome stays alive after its last window is closed, and a windowless Chrome refuses Playwright's
    attach ("Browser context management is not supported"). Open a blank tab so there is always one to attach to."""
    try:
        if _page_count(url) == 0:
            urllib.request.urlopen(urllib.request.Request(f"{url}/json/new?about:blank", method="PUT"), timeout=3).close()
    except Exception:
        pass


def ensure_running(url: str | None = None, wait_s: float = 10, popen=subprocess.Popen,
                   is_up=None, window=None) -> str | None:
    """None once the agent browser answers on its debug port with a window open (launching it if needed), else a
    reason. Never raises."""
    from urllib.parse import urlparse
    url, is_up, window = url or cdp_url(), is_up or reachable, window or ensure_window
    if is_up(url):
        window(url)
        return None
    host = urlparse(url).hostname or ""
    if host not in ("127.0.0.1", "localhost", "::1"):
        return f"agent browser at {url} is not reachable (remote CDP URLs are not auto-launched)"
    exe = _executable()
    if not exe:
        return "no Chrome/Chromium found — install Google Chrome or set AGENT_CHROME_PATH"
    paths.BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    popen([exe, *launch_args(urlparse(url).port or 9333)],
          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if is_up(url):
            return None
        time.sleep(0.5)
    return f"launched the agent browser but it didn't answer at {url} within {wait_s:.0f}s"
