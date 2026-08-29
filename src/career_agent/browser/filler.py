"""Execute fill decisions against a live page, and read values back for
verification. Never clicks submit — that is the run loop's decision."""
from __future__ import annotations

from ..orchestrator.mapper import FillDecision


# Any fill action can legitimately fail on a real form (an unmatched option, a
# hidden file input, or a field that turns out disabled/read-only). None may
# hang or abort the whole run — every action fails fast and leaves the field
# for the human. (A live reCAPTCHA demo has a disabled decoy input that, filled
# strictly, blocked for 30s and crashed the run — never again.)
_SOFT_TIMEOUT_MS = 4000


def apply_decisions(page, decisions: list[FillDecision]) -> None:
    for d in decisions:
        if d.value is None:
            continue
        if d.action == "fill":
            try:
                page.fill(d.ref, str(d.value), timeout=_SOFT_TIMEOUT_MS)
            except Exception:
                pass
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
        elif d.action == "check":
            # tick a single checkbox (a required attestation draft). Binding is
            # the SUBMIT, which stays human-gated — see screen_review.
            try:
                page.check(d.ref, timeout=_SOFT_TIMEOUT_MS)
            except Exception:
                pass
        # review: intentionally left for the human.


def read_back(page, decisions: list[FillDecision]) -> dict:
    out: dict[str, str] = {}
    for d in decisions:
        if d.action in ("fill", "select") and d.ref.startswith(("#", "[")):
            try:
                out[d.ref] = page.input_value(d.ref)
            except Exception:
                pass
    return out
