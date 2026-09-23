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

# hcaptcha_checkbox = invisible widget present, no visual challenge — the form
# is still accessible; only the submit button needs the token. Proceed through
# fill; re-check only at submit time.
_SUBMIT_GATED = {"hcaptcha_checkbox"}


def _page_survey(page, label: str) -> None:
    """Navigation rule (mandatory): scroll-to-top + full-page screenshot before
    reading DOM or acting on any screen. Captures the visual state we are about
    to reason over so clicks are never made blind."""
    try:
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(300)
        ss = f"/tmp/career_agent_{label}_survey.png"
        page.screenshot(path=ss, full_page=True)
        print(f"[nav] survey → {ss}", flush=True)
    except Exception:
        pass


def _blocking(gate: str) -> bool:
    # Any gate whose handler is not "proceed" blocks the walk. Checking against
    # "proceed" (not against "escalate") is deliberate: otp_email routes to its
    # own handler string, so an == "escalate" test would wrongly let an OTP
    # screen fall through to fill/advance — a boundary violation.
    return HANDLERS.get(gate, "escalate") != "proceed"


def walk(page, profile, human, deps, max_steps=15, do_submit=False,
         autonomous=False, on_link=None, resume_pdf=None, judge_fn=None,
         prep_fn=None, learn=None, vision_fn=None, cred_provider=None) -> dict:
    submitted, reason, steps = False, "max_steps", 0
    for _ in range(max_steps):
        steps += 1
        if prep_fn is not None:
            prep_fn(page)               # clear cookie/idle overlays before perceiving

        # Gate check first — hCaptcha auto-verifies asynchronously on trusted
        # browsers; poll until cleared (up to 5s) before snapshotting the form.
        gate = deps.gate(page)
        if gate in INTERACTIVE_GATES:
            for _ in range(5):          # 5 × 1s = 5s max auto-verify window
                page.wait_for_timeout(1000)
                gate = deps.gate(page)
                if not _blocking(gate):
                    break
        if _blocking(gate):
            if gate in _SUBMIT_GATED:
                # Invisible checkbox with no visual challenge — form is still
                # accessible; escalate at submit time, not now.
                print(f"[gate] {gate} — form accessible, deferring to submit")
            elif gate in INTERACTIVE_GATES:
                print(f"[gate] {gate} — sending live-view link via Telegram...")
                if not human.remote_solve(page, gate, on_link or (lambda u: None)):
                    reason = f"gate:{gate}"; break
                if _blocking(deps.gate(page)):   # solve didn't actually clear it
                    reason = f"gate:{gate}"; break
            else:
                reason = f"gate:{gate}"; break   # OTP / cloudflare / etc -> stop

        # Mid-walk account-creation / login wall: iCIMS shows a "Create a login"
        # form on screen 2. classify_entry() catches it; credential_provider fills
        # and submits so walk() can continue past the auth screen.
        if cred_provider is not None:
            from ..browser.page_prep import classify_entry, clear_auth_wall
            _kind = classify_entry(page)
            if _kind in ("password", "email_auth"):
                print(f"[cred] {_kind} wall — credential provider...", flush=True)
                clear_auth_wall(page, credential_provider=cred_provider)
                if classify_entry(page) in ("password", "email_auth"):
                    reason = "auth_wall"; break

        _page_survey(page, f"step{steps}")    # navigation rule: see page before acting
        print("[step] snapshot...", flush=True)
        form = deps.snapshot(page)
        print(f"[step] {len(form)} fields; LLM={judge_fn is not None}", flush=True)
        if vision_fn is not None:              # read labels the DOM couldn't (vision fallback)
            from ..browser.perception import enrich_with_vision
            form = enrich_with_vision(page, form, vision_fn)

        # Recall FIRST — a learned answer/correction wins over the rules, so a
        # field the rules once filled wrong (address="Yes") is fixed for good.
        fillable = [f for f in form if f.kind != "button"]
        recalled, remaining = ([], fillable)
        if learn is not None:
            recalled, remaining = learn.recall(fillable)
        decisions, needs = map_screen(remaining, profile, resume_pdf)
        decisions += recalled
        if needs and judge_fn is not None:
            answered, needs, _flagged = judge_fn(needs)   # tier 2/3 before the human
            decisions += answered
        if needs:
            human_answers = human.collect(needs)
            decisions += apply_answers(needs, human_answers)
            if learn is not None:                         # remember for next time
                for f in needs:
                    if human_answers.get(f.ref) is not None:
                        learn.record(f, human_answers[f.ref])
        print(f"[fill] screen {steps}: {len(decisions)} decisions, {len(needs)} escalated")
        deps.fill(page, decisions)
        try:
            _ss = f"/tmp/career_agent_step{steps}_filled.png"
            page.screenshot(path=_ss, full_page=True)
            print(f"[screenshot] {_ss}", flush=True)
        except Exception:
            pass

        # One extra pass for conditional fields revealed during fill (e.g. Phenom
        # applicantSource appears after sourceType="Job Board" is selected).
        _seen = {f.ref for f in form}
        _form2 = deps.snapshot(page)
        _new = [f for f in _form2 if f.kind != "button" and f.ref not in _seen]
        if _new:
            _d2, _n2 = map_screen(_new, profile, resume_pdf)
            if _n2 and judge_fn is not None:
                _a2, _n2, _ = judge_fn(_n2)
                _d2 += _a2
            if _n2:
                _d2 += apply_answers(_n2, human.collect(_n2))
            if _d2:
                deps.fill(page, _d2)
                decisions.extend(_d2)

        before = screen_signature(deps.url(page), form)
        has_advance = has_control(form, ADVANCE_NAMES)
        has_submit = has_control(form, SUBMIT_NAMES)

        if not has_advance and has_submit:          # final screen: submit
            if not do_submit:
                reason = "reached_submit_dry_run"; break
            # Pre-submit gate re-check: hcaptcha_checkbox deferred from fill
            # time must be cleared before the button is clicked.
            pre_gate = deps.gate(page)
            if _blocking(pre_gate):
                if pre_gate in INTERACTIVE_GATES:
                    print(f"[gate] pre-submit {pre_gate} — sending live-view link via Telegram...")
                    if not human.remote_solve(page, pre_gate, on_link or (lambda u: None)):
                        reason = f"gate:{pre_gate}"; break
                    if _blocking(deps.gate(page)):
                        reason = f"gate:{pre_gate}"; break
                else:
                    reason = f"gate:{pre_gate}"; break
            if autonomous or human.approve("Ready to submit"):
                # the human just reviewed/edited the live form -> learn from any
                # change (final value != what we filled) before submitting.
                if learn is not None and hasattr(deps, "read_back"):
                    try:
                        learn.record_corrections(form, decisions, deps.read_back(page, decisions))
                    except Exception:
                        pass
                deps.click(page, pick_advance_label(form, is_last=True))
                submitted = True; reason = "submitted"
            else:
                reason = "submit_declined"
            break
        if not has_advance:
            reason = "no_advance_control"; break

        try:
            deps.click(page, pick_advance_label(form, is_last=False))
        except Exception:
            reason = "advance_failed"; break   # advance label matched but wasn't clickable
        # The advance click may trigger a captcha asynchronously (e.g. invisible
        # hCaptcha on iCIMS shows the image challenge after the click, not before).
        # Re-check the gate here so we can remote-solve before reading the next screen.
        _post_gate = deps.gate(page)
        if _post_gate in INTERACTIVE_GATES and _blocking(_post_gate):
            if _post_gate not in _SUBMIT_GATED:
                print(f"[gate] post-advance {_post_gate} — sending live-view link via Telegram...")
                if not human.remote_solve(page, _post_gate, on_link or (lambda u: None)):
                    reason = f"gate:{_post_gate}"; break
                if _blocking(deps.gate(page)):
                    reason = f"gate:{_post_gate}"; break
        after = screen_signature(deps.url(page), deps.snapshot(page))
        if not changed(before, after):
            reason = "stuck"; break

    return {"screens": steps, "submitted": submitted, "stopped_reason": reason, "cards": []}
