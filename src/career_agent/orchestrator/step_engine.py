"""The multi-page walk: perceive -> gate -> fill -> escalate unknowns -> advance
-> detect change -> repeat, until submit / terminal / cap. Browser ops come via
`deps` so the loop is testable without Playwright."""
from __future__ import annotations

from ..browser.gate_probe import HANDLERS
from ..orchestrator.screen_review import map_screen, apply_answers
from ..orchestrator.advance import (
    screen_signature, changed, pick_advance_label, has_control,
    ADVANCE_NAMES, SUBMIT_NAMES,
)

INTERACTIVE_GATES = {"recaptcha_v2_checkbox", "recaptcha_v2_image",
                     "hcaptcha_checkbox", "hcaptcha_image"}


def _blocking(gate: str) -> bool:
    # Any gate whose handler is not "proceed" blocks the walk. Checking against
    # "proceed" (not against "escalate") is deliberate: otp_email routes to its
    # own handler string, so an == "escalate" test would wrongly let an OTP
    # screen fall through to fill/advance — a boundary violation.
    return HANDLERS.get(gate, "escalate") != "proceed"


def walk(page, profile, human, deps, max_steps=15, do_submit=False,
         autonomous=False, on_link=None, resume_pdf=None, judge_fn=None) -> dict:
    submitted, reason, steps = False, "max_steps", 0
    for _ in range(max_steps):
        steps += 1
        form = deps.snapshot(page)

        gate = deps.gate(page)
        if _blocking(gate):
            if gate in INTERACTIVE_GATES:
                if not human.remote_solve(page, gate, on_link or (lambda u: None)):
                    reason = f"gate:{gate}"; break
                if _blocking(deps.gate(page)):   # solve didn't actually clear it
                    reason = f"gate:{gate}"; break
            else:
                reason = f"gate:{gate}"; break   # OTP / cloudflare / etc -> stop

        decisions, needs = map_screen(form, profile, resume_pdf)
        if needs and judge_fn is not None:
            answered, needs, _flagged = judge_fn(needs)   # tier 2/3 before the human
            decisions += answered
        if needs:
            decisions += apply_answers(needs, human.collect(needs))
        deps.fill(page, decisions)

        before = screen_signature(deps.url(page), form)
        has_advance = has_control(form, ADVANCE_NAMES)
        has_submit = has_control(form, SUBMIT_NAMES)

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
