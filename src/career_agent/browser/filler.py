"""Execute fill decisions against a live page, and read values back for
verification. Never clicks submit — that is the run loop's decision."""
from __future__ import annotations

from ..orchestrator.mapper import FillDecision
from ..orchestrator.screen_review import _coerce_option
from .perception import frame_target, split_ref


# Any fill action can legitimately fail on a real form (an unmatched option, a
# hidden file input, or a field that turns out disabled/read-only). None may
# hang or abort the whole run — every action fails fast and leaves the field
# for the human. (A live reCAPTCHA demo has a disabled decoy input that, filled
# strictly, blocked for 30s and crashed the run — never again.)
_SOFT_TIMEOUT_MS = 4000


def apply_decisions(page, decisions: list[FillDecision], matcher=None) -> None:
    for d in decisions:
        if d.value is None:
            continue
        # Resolve which frame this field lives in (an embedded ATS iframe fills
        # via its own frame, not the top page); `sel` is the bare selector there.
        target, sel = frame_target(page, d.ref)
        if d.action == "combobox":
            # React "fake dropdown": open it, read the live options, map our
            # value to one (exact/word via _coerce_option, else the injected
            # llm matcher), and click it. No match -> leave blank for the human.
            try:
                target.click(sel, timeout=_SOFT_TIMEOUT_MS)
                page.wait_for_timeout(300)      # let the listbox render
                # Scope to the listbox THIS combobox controls — reading every
                # [role=option] on the page grabs unrelated widgets (e.g. the
                # phone-country list has 247 options, one of them "Male").
                lb_id = target.get_attribute(sel, "aria-controls")
                scope = target.locator(f"#{lb_id}") if lb_id else target
                options = [t.strip() for t in
                           scope.locator("[role=option]").all_text_contents() if t.strip()]
                opt = _coerce_option(str(d.value), options)
                if opt is None and matcher is not None:
                    opt = matcher(d.label, str(d.value), options)
                if opt:
                    scope.get_by_role("option", name=opt, exact=True).first.click(
                        timeout=_SOFT_TIMEOUT_MS)
                else:
                    page.keyboard.press("Escape")
            except Exception:
                pass
            continue
        if d.action == "fill":
            try:
                target.fill(sel, str(d.value), timeout=_SOFT_TIMEOUT_MS)
            except Exception:
                pass
        elif d.action == "select":
            try:
                target.select_option(sel, label=str(d.value), timeout=_SOFT_TIMEOUT_MS)
            except Exception:
                pass
        elif d.action == "upload":
            try:
                target.set_input_files(sel, str(d.value), timeout=_SOFT_TIMEOUT_MS)
            except Exception:
                pass
        elif d.action == "check_group":
            # value is the intended option label; click the matching radio.
            try:
                target.get_by_label(str(d.value), exact=True).check(timeout=_SOFT_TIMEOUT_MS)
            except Exception:
                pass
        elif d.action == "check":
            # tick a single checkbox (a required attestation draft). Binding is
            # the SUBMIT, which stays human-gated — see screen_review.
            try:
                target.check(sel, timeout=_SOFT_TIMEOUT_MS)
            except Exception:
                pass
        # review: intentionally left for the human.


def read_back(page, decisions: list[FillDecision]) -> dict:
    out: dict[str, str] = {}
    for d in decisions:
        _idx, sel = split_ref(d.ref)
        if d.action in ("fill", "select", "combobox") and sel.startswith(("#", "[")):
            try:
                target, s = frame_target(page, d.ref)
                out[d.ref] = target.input_value(s)
            except Exception:
                pass
    return out
