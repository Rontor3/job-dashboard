"""Persistent-context Chrome launcher. A real on-disk profile so sessions and
cookies persist across runs, headed by default.

CDP mode: pass cdp_url (e.g. "http://localhost:9222") to attach to an
already-running Chrome instead of launching a new one.  close() disconnects
cleanly without killing the user's browser.
"""
from __future__ import annotations

from pathlib import Path


def launch(settings, cdp_url: str | None = None):
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    if cdp_url:
        browser = pw.chromium.connect_over_cdp(cdp_url)
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
