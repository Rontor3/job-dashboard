"""Park mode (--park): run unattended for the dashboard's apply queue.

Nothing here waits on the human. Questions the answer ladder cannot fill are
left open (the run ends needs_human and they sit in application_qa for the
tracker), a single non-blocking note says how many were parked, and every
approval is a "no" so best-guess answers are never submitted unseen.
--result-json hands the queue runner a small, stable summary of the run.
"""
from __future__ import annotations

import json

from .approver import AutoDenyApprover
from .human_loop import HumanLoop


class ParkCollector:
    """HumanLoop collector contract (fields -> {ref: value}) that answers nothing."""
    parks = True                     # _run_graph stops asking instead of retrying

    def __init__(self, notify=None):
        self.notify = notify
        self.context = None          # set by boards.run: "Naukri — ML Engineer"

    def __call__(self, fields) -> dict:
        if not fields:
            return {}
        labels = ", ".join((f.label or f.ref)[:60] for f in fields[:6])
        msg = (f"⏸ {len(fields)} question(s) parked for {self.context or 'this job'}: {labels}"
               " — answer them on the tracker, then re-queue.")
        print(f"[park] {msg}", flush=True)
        if self.notify:
            try:
                self.notify(msg)
            except Exception as e:
                print(f"[park] notify failed ({type(e).__name__})", flush=True)
        return {}


def park_human(notify=None) -> HumanLoop:
    return HumanLoop(AutoDenyApprover(), remote_solve_factory=None, collector=ParkCollector(notify))


def result_summary(out: dict | None) -> dict:
    out = out or {"stopped_reason": "error"}
    pending = out.get("pending_human") or []
    return {"url": out.get("url"), "board": out.get("board"),
            "submitted": bool(out.get("submitted")),
            "stopped_reason": out.get("stopped_reason") or "error",
            "filled": len(out.get("decisions") or []),
            "pending_human": [(p.get("label") or p.get("ref")) if isinstance(p, dict) else str(p)
                              for p in pending]}


def write_result(path, out) -> None:
    if not path:
        return
    try:
        with open(path, "w") as fh:
            json.dump(result_summary(out), fh)
    except Exception as e:
        print(f"[result] could not write {path} ({type(e).__name__})", flush=True)
