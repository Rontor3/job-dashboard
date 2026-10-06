"""FillDecision: the per-field fill instruction the whole pipeline speaks in.

The live mapper is `screen_review.map_screen`; this module holds only the
shared dataclass and the kind->action helper it (and the filler) depend on."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FillDecision:
    ref: str
    kind: str
    label: str
    value: object
    action: str
    source: str


def _action_for_kind(kind: str) -> str:
    if kind == "select":
        return "select"
    if kind == "radio_group":
        return "check_group"
    if kind == "combobox":
        return "combobox"           # open the fake dropdown + click a live option
    if kind in ("datepicker", "date_parts"):
        return kind                 # read-only calendar popup / separate day-month-year boxes (browser/date_widgets.py)
    return "fill"
