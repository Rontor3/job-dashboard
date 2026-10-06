"""Screen-signature change detection + choosing the advance control's label.
Pure; the actual click is done by the step engine via Playwright get_by_role."""
from __future__ import annotations

import re
from urllib.parse import urlparse

ADVANCE_NAMES = ["save and continue", "continue", "next", "review", "save & continue", "start"]
SUBMIT_NAMES = ["submit application", "submit", "send application", "send", "apply", "finish", "confirm"]
NEVER_NAMES = ["back", "cancel", "previous", "logout", "sign out",
               # session / idle dialogs and the Oracle chat widget — never
               # advance targets (e.g. "Continue Working" contains "continue").
               "continue working", "end session", "discard", "add summary",
               "skip to main", "back to job",
               # OAuth/SSO shortcuts — not the real application submit button
               "apply with"]


def screen_signature(url, form):
    return (urlparse(url).path, frozenset(f.label.strip().lower() for f in form if f.label))


def changed(before, after):
    return before != after


_ADVANCE_TAIL = {"step", "page", "to", "the", "next", "application", "review", "questions", "section", "and", "continue",
                 "save", "proceed", "now", "form", "start"}


def _advance_match(label_low: str, cand: str) -> bool:
    """A wizard's Next/Continue-style button, not any link that merely contains the word: the label must BEGIN with the
    advance phrase as whole tokens and carry at most a few filler words after it. "Next >", "Continue to review" and
    "Save and continue" match; "Next.js", "Next JS Developer" (a job link) and "Start a free trial" do not."""
    toks = re.findall(r"[a-z0-9.+#']+", label_low.replace("&", " and "))
    ct = cand.replace("&", " and ").split()
    if toks[:len(ct)] != ct:
        return False
    tail = toks[len(ct):]
    return len(tail) <= 3 and all(t in _ADVANCE_TAIL for t in tail)


def _matches(label_low: str, cand: str) -> bool:
    # Whole-word/phrase match, never a Back/Cancel-style control. Word
    # boundaries stop 'confirm' matching 'confirmation', 'apply' matching
    # 'reapply', 'finish' matching 'finished' — the old substring test allowed
    # all three, so a status/label screen could be mistaken for the submit step.
    if any(bad in label_low for bad in NEVER_NAMES):
        return False
    if cand in ADVANCE_NAMES:
        return _advance_match(label_low, cand)
    return re.search(r"\b" + re.escape(cand) + r"\b", label_low) is not None


def has_control(form, names) -> bool:
    """Is a control of this family (advance / submit) present, ignoring
    Back/Cancel? Used to tell an advance step from a submit-only step."""
    return any(_matches(f.label.strip().lower(), cand)
               for f in form if f.label for cand in names)


def advance_names(form):
    """ADVANCE_NAMES for this screen. "review" is a weak advance word: a wizard's stepper ("... > Review > Submit") and its
    last page's heading carry it too. Where a Submit control is present, the screen is the final one and "review" is not
    a button to press (pressing it did nothing and the run was parked as stuck)."""
    if has_control(form, SUBMIT_NAMES):
        return [n for n in ADVANCE_NAMES if n != "review"]
    return list(ADVANCE_NAMES)


def pick_advance_label(form, is_last):
    lowered = {f.label.strip().lower(): f.label.strip() for f in form if f.label}
    adv = advance_names(form)
    order = (SUBMIT_NAMES + adv) if is_last else (adv + SUBMIT_NAMES)
    for cand in order:
        for low, orig in lowered.items():
            if _matches(low, cand):
                return orig
    return None
