"""Execute fill decisions against a live page, and read values back for
verification. Never clicks submit — that is the run loop's decision."""
from __future__ import annotations

from ..orchestrator.mapper import FillDecision


# Option/upload actions can legitimately fail on a real form (an option label
# that doesn't match, a hidden file input). They must never hang or abort the
# whole run — fail fast and leave the field for the human. Text fills stay
# strict: those are direct profile values that should always apply.
_SOFT_TIMEOUT_MS = 4000


def apply_decisions(page, decisions: list[FillDecision]) -> None:
    for d in decisions:
        if d.value is None:
            continue
        if d.action == "fill":
            page.fill(d.ref, str(d.value))
        elif d.action == "select":
            try:
                page.select_option(d.ref, label=str(d.value), timeout=_SOFT_TIMEOUT_MS)
            except Exception:
                pass
        elif d.action == "upload":
            try:
                page.set_input_files(d.ref, str(d.value), timeout=_SOFT_TIMEOUT_MS)
            except Exception:
                pass
        elif d.action == "check_group":
            # value is the intended option label; click the matching radio.
            try:
                page.get_by_label(str(d.value), exact=True).check(timeout=_SOFT_TIMEOUT_MS)
            except Exception:
                pass
        # review / attestation: intentionally left for the human.


def read_back(page, decisions: list[FillDecision]) -> dict:
    out: dict[str, str] = {}
    for d in decisions:
        if d.action in ("fill", "select") and d.ref.startswith(("#", "[")):
            try:
                out[d.ref] = page.input_value(d.ref)
            except Exception:
                pass
    return out
