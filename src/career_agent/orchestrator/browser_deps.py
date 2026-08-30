"""Playwright-backed browser ops for the step engine (kept thin; the engine
holds the logic)."""
from __future__ import annotations


class BrowserDeps:
    def __init__(self, option_matcher=None):
        self.option_matcher = option_matcher   # rung-3 value->option llm (comboboxes)

    def snapshot(self, page):
        from ..browser.perception import snapshot_form
        return snapshot_form(page)

    def gate(self, page):
        from ..browser.gate_probe import classify_gate
        return classify_gate(page)

    def fill(self, page, decisions):
        from ..browser.filler import apply_decisions
        apply_decisions(page, decisions, matcher=self.option_matcher)

    def click(self, page, label):
        try:
            page.get_by_role("button", name=label).first.click(timeout=8000)
        except Exception:
            page.get_by_role("link", name=label).first.click(timeout=8000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

    def url(self, page):
        return page.url
