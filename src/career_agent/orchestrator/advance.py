"""Screen-signature change detection + choosing the advance control's label.
Pure; the actual click is done by the step engine via Playwright get_by_role."""
from __future__ import annotations

from urllib.parse import urlparse

ADVANCE_NAMES = ["save and continue", "continue", "next", "review", "save & continue"]
SUBMIT_NAMES = ["submit application", "submit", "apply", "finish", "confirm"]
NEVER_NAMES = ["back", "cancel", "previous", "logout", "sign out"]


def screen_signature(url, form):
    return (urlparse(url).path, frozenset(f.label.strip().lower() for f in form if f.label))


def changed(before, after):
    return before != after


def _labels(form):
    return [f.label.strip() for f in form if f.label]


def pick_advance_label(form, is_last):
    labels = _labels(form)
    lowered = {l.lower(): l for l in labels}
    order = (SUBMIT_NAMES + ADVANCE_NAMES) if is_last else (ADVANCE_NAMES + SUBMIT_NAMES)
    for cand in order:
        for low, orig in lowered.items():
            if cand in low and not any(bad in low for bad in NEVER_NAMES):
                return orig
    return None
