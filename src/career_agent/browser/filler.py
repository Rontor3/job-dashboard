"""Execute fill decisions against a live page, and read values back for
verification. Never clicks submit — that is the run loop's decision."""
from __future__ import annotations

from ..orchestrator.mapper import FillDecision


def apply_decisions(page, decisions: list[FillDecision]) -> None:
    for d in decisions:
        if d.value is None:
            continue
        if d.action == "fill":
            page.fill(d.ref, str(d.value))
        elif d.action == "select":
            page.select_option(d.ref, label=str(d.value))
        elif d.action == "upload":
            page.set_input_files(d.ref, str(d.value))
        elif d.action == "check_group":
            # value is the intended option label; click the matching radio.
            page.get_by_label(str(d.value)).check()
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
