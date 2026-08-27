"""The multi-page walk: perceive -> gate -> fill -> escalate unknowns -> advance
-> detect change -> repeat, until submit / terminal / cap. Browser ops come via
`deps` so the loop is testable without Playwright."""
from __future__ import annotations

from ..browser.gate_probe import HANDLERS
from ..orchestrator.screen_review import map_screen, apply_answers
from ..orchestrator.advance import (
    screen_signature, changed, pick_advance_label,
    ADVANCE_NAMES, SUBMIT_NAMES, NEVER_NAMES,
)

INTERACTIVE_GATES = {"recaptcha_v2_checkbox", "recaptcha_v2_image",
                     "hcaptcha_checkbox", "hcaptcha_image"}


def _has_control(form, names):
    """Is a control of this family (advance / submit) present, ignoring
    Back/Cancel? Used instead of `pick_advance_label(...) is None`, which can't
    tell an advance step from a submit step (it falls back across families)."""
    labels = [f.label.strip().lower() for f in form if f.label]
    return any(cand in l and not any(bad in l for bad in NEVER_NAMES)
               for l in labels for cand in names)


def walk(page, profile, human, deps, max_steps=15, do_submit=False,
         autonomous=False, on_link=None) -> dict:
    submitted, reason, steps = False, "max_steps", 0
    for _ in range(max_steps):
        steps += 1
        form = deps.snapshot(page)

        gate = deps.gate(page)
        if HANDLERS.get(gate, "escalate") == "escalate":
            if gate in INTERACTIVE_GATES:
                if not human.remote_solve(page, gate, on_link or (lambda u: None)):
                    reason = f"gate:{gate}"; break
                gate = deps.gate(page)          # re-read after the human solved it
            else:
                reason = f"gate:{gate}"; break   # OTP / cloudflare / etc -> stop

        decisions, needs = map_screen(form, profile)
        if needs:
            decisions += apply_answers(needs, human.collect(needs))
        deps.fill(page, decisions)

        before = screen_signature(deps.url(page), form)
        has_advance = _has_control(form, ADVANCE_NAMES)
        has_submit = _has_control(form, SUBMIT_NAMES)

        if not has_advance and has_submit:          # final screen: submit
            if not do_submit:
                reason = "reached_submit_dry_run"; break
            if autonomous or human.approve("Ready to submit"):
                deps.click(page, pick_advance_label(form, is_last=True))
                submitted = True; reason = "submitted"
            else:
                reason = "submit_declined"
            break
        if not has_advance:
            reason = "no_advance_control"; break

        deps.click(page, pick_advance_label(form, is_last=False))
        after = screen_signature(deps.url(page), deps.snapshot(page))
        if not changed(before, after):
            reason = "stuck"; break

    return {"screens": steps, "submitted": submitted, "stopped_reason": reason, "cards": []}
