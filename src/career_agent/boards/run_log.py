"""Per-page record of a board run, for the tracker's "Last agent run".

One screenshot per page, taken AFTER the page is filled (`perceive<N>.png`, the same naming
the career-site graph uses; a long page adds `perceive<N>_2.png`, ...) plus a final one where the run stopped, and
`board_run.json` = [{step, kind, url, stopped_reason, pending_human,
screenshot}] — the shape run_history.summarize_run returns for graph runs.
Best-effort throughout: logging must never break an application.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..browser.page_shot import capture_page

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

    def _add(self, page, kind, stopped_reason=None, pending=None, shot=False) -> None:
        step = {"step": len(self.steps), "kind": kind, "url": getattr(page, "url", None),
                "stopped_reason": stopped_reason, "pending_human": pending or [],
                "screenshot": None, "screenshots": []}
        self.steps.append(step)
        if shot:
            self._capture(page, step)

    def _capture(self, page, step: dict) -> None:
        paths = capture_page(page, str(self.dir / f"perceive{step['step']}"))
        step["screenshots"], step["screenshot"] = paths, (paths[0] if paths else None)

    def page(self, page) -> int:
        """Before the driver reads a page; its page number (counted even when logging is off)."""
        n, self._pages = self._pages, self._pages + 1
        if self.dir is not None:
            self._add(page, "form")
        return n

    def filled(self, page) -> None:
        """The current page after its answers are typed, before moving on (re-called to refresh)."""
        if self.dir is not None and self.steps and self.steps[-1]["kind"] == "form":
            self._capture(page, self.steps[-1])

    def finish(self, page, reason: str, pending: list) -> None:
        if self.dir is None:
            return
        if self.steps and self.steps[-1]["kind"] == "form" and not self.steps[-1]["screenshot"]:
            self._capture(page, self.steps[-1])           # stopped before filling this page: show where it stopped
        self._add(page, "stop", reason, pending, shot=True)
        try:
            (self.dir / RESULT).write_text(json.dumps(self.steps))
        except OSError:
            pass
