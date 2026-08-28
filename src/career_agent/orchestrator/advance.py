"""Screen-signature change detection + choosing the advance control's label.
Pure; the actual click is done by the step engine via Playwright get_by_role."""
from __future__ import annotations

import re
from urllib.parse import urlparse

ADVANCE_NAMES = ["save and continue", "continue", "next", "review", "save & continue"]
SUBMIT_NAMES = ["submit application", "submit", "apply", "finish", "confirm"]
NEVER_NAMES = ["back", "cancel", "previous", "logout", "sign out",
               # session / idle dialogs and the Oracle chat widget — never
               # advance targets (e.g. "Continue Working" contains "continue").
               "continue working", "end session", "discard", "add summary",
               "skip to main", "back to job"]


def screen_signature(url, form):
    return (urlparse(url).path, frozenset(f.label.strip().lower() for f in form if f.label))


def changed(before, after):
    return before != after


def _matches(label_low: str, cand: str) -> bool:
    # Whole-word/phrase match, never a Back/Cancel-style control. Word
    # boundaries stop 'confirm' matching 'confirmation', 'apply' matching
    # 'reapply', 'finish' matching 'finished' — the old substring test allowed
    # all three, so a status/label screen could be mistaken for the submit step.
    if any(bad in label_low for bad in NEVER_NAMES):
        return False
    return re.search(r"\b" + re.escape(cand) + r"\b", label_low) is not None


def has_control(form, names) -> bool:
    """Is a control of this family (advance / submit) present, ignoring
    Back/Cancel? Used to tell an advance step from a submit-only step."""
    return any(_matches(f.label.strip().lower(), cand)
               for f in form if f.label for cand in names)


def pick_advance_label(form, is_last):
    lowered = {f.label.strip().lower(): f.label.strip() for f in form if f.label}
    order = (SUBMIT_NAMES + ADVANCE_NAMES) if is_last else (ADVANCE_NAMES + SUBMIT_NAMES)
    for cand in order:
        for low, orig in lowered.items():
            if _matches(low, cand):
                return orig
    return None
