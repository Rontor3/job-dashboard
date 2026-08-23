"""Phase-1 entrypoint: one application pass over a target URL.

perceive -> classify gate -> map -> fill -> compose card -> approve -> (maybe) submit.
Dry-run by default; submits only on explicit approval AND a clear gate."""
from __future__ import annotations

import argparse

from .browser.perception import snapshot_form
from .browser.gate_probe import classify_gate, HANDLERS
from .browser.filler import apply_decisions
from .orchestrator.mapper import map_fields
from .integrations.review_card import render_card
from .integrations.approver import CliApprover


def _click_submit(page) -> None:
    # Prefer an explicit hook (tests), else a best-effort submit button.
    if hasattr(page, "click_submit"):
        page.click_submit()
    else:
        page.get_by_role("button", name="Submit").click()


def run_once(page, profile, resume_path, meta, approver, do_submit) -> dict:
    form = snapshot_form(page)
    gate = classify_gate(page)
    decisions = map_fields(form, profile, resume_path)
    apply_decisions(page, decisions)
    card = render_card(meta["company"], meta["role"], meta["portal"], decisions, gate)

    gate_clear = HANDLERS.get(gate, "escalate") == "proceed"
    approved = False
    submitted = False
    if do_submit and gate_clear:
        approved = approver.request(card)
        if approved:
            _click_submit(page)
            submitted = True

    return {"gate": gate, "card": card, "approved": approved,
            "submitted": submitted, "decisions": decisions}


def main() -> None:
    from .config.settings import load_settings
    from .browser.runner import launch, close
    from .memory.factual_core import load_profile

    ap = argparse.ArgumentParser(description="Career agent — Phase 1 harness")
    ap.add_argument("--url", required=True)
    ap.add_argument("--submit", action="store_true", help="actually submit (default: dry-run)")
    ap.add_argument("--company", default="(unknown)")
    ap.add_argument("--role", default="(unknown)")
    ap.add_argument("--resume", default=None)
    ap.add_argument("--profile", default="profile.json")
    args = ap.parse_args()

    settings = load_settings()
    profile = load_profile(args.profile)
    pw, context, page = launch(settings)
    try:
        page.goto(args.url)
        meta = {"company": args.company, "role": args.role, "portal": args.url}
        out = run_once(page, profile, args.resume, meta, CliApprover(), args.submit)
        print(out["card"])
        print(f"\n[gate={out['gate']}] submitted={out['submitted']}")
    finally:
        close(pw, context)


if __name__ == "__main__":
    main()
