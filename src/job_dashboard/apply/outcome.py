"""Map one career_agent run (its --result-json dict + exit code) to the apply
queue's verdict: (queue state, reason, application status or None).

A submission the board confirmed is always "done/applied", even if the process
crashed afterwards. Anything that stopped short without crashing is "parked"
for the human; only a crash or a missing result is "failed".
"""
from __future__ import annotations

_RENAME = {"ready_for_review": "review", "apply_is_one_click": "one_click_needs_autosubmit"}


def outcome(result: dict | None, exit_code: int) -> tuple[str, str, str | None]:
    if result and result.get("submitted"):
        return "done", "submitted", "applied"
    if result is None:
        return "failed", "crashed" if exit_code else "no_result", "failed"
    reason = result.get("stopped_reason") or "stopped"
    if exit_code:
        return "failed", reason, "failed"
    if result.get("pending_human"):
        return "parked", "needs_answers", None
    return "parked", _RENAME.get(reason, reason), None
