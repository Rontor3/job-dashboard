"""Per-page record of a board run, for the tracker's "Last agent run".

One screenshot per page the driver reads (`perceive<N>.png`, the same naming
the career-site graph uses) plus a final one where the run stopped, and
`board_run.json` = [{step, kind, url, stopped_reason, pending_human,
screenshot}] — the shape run_history.summarize_run returns for graph runs.
Best-effort throughout: logging must never break an application.
"""
from __future__ import annotations

import json
from pathlib import Path

RESULT = "board_run.json"


class BoardRunLog:
    def __init__(self, run_dir: str | None):
        self.dir = Path(run_dir) if run_dir else None
        self.steps: list[dict] = []
        self._pages = 0
        if self.dir is None:
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            for old in [*self.dir.glob("perceive*.png"), self.dir / RESULT]:
                old.unlink(missing_ok=True)          # the last run only, never a mix
        except OSError:
            self.dir = None

    def _shot(self, page) -> str | None:
        path = self.dir / f"perceive{len(self.steps)}.png"
        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(300)
            page.screenshot(path=str(path), full_page=True, timeout=5000)
            return str(path)
        except Exception:
            return None

    def _add(self, page, kind, stopped_reason=None, pending=None) -> None:
        self.steps.append({"step": len(self.steps), "kind": kind, "url": getattr(page, "url", None),
                           "stopped_reason": stopped_reason, "pending_human": pending or [],
                           "screenshot": self._shot(page)})

    def page(self, page) -> int:
        """Before the driver reads a page; its page number (counted even when logging is off)."""
        n, self._pages = self._pages, self._pages + 1
        if self.dir is not None:
            self._add(page, "form")
        return n

    def finish(self, page, reason: str, pending: list) -> None:
        if self.dir is None:
            return
        self._add(page, "stop", reason, pending)
        try:
            (self.dir / RESULT).write_text(json.dumps(self.steps))
        except OSError:
            pass
