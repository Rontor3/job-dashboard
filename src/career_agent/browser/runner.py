"""Persistent-context Chrome launcher. A real on-disk profile so sessions and
cookies persist across runs, headed by default."""
from __future__ import annotations

from pathlib import Path


def launch(settings):
    from playwright.sync_api import sync_playwright
    Path(settings.user_data_dir).mkdir(parents=True, exist_ok=True)
    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        settings.user_data_dir, headless=not settings.headed,
    )
    page = context.pages[0] if context.pages else context.new_page()
    return pw, context, page


def close(pw, context) -> None:
    try:
        context.close()
    finally:
        pw.stop()
