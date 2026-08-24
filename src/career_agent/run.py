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
from .integrations.human_loop import HumanLoop

INTERACTIVE_GATES = {"recaptcha_v2_checkbox", "recaptcha_v2_image",
                     "hcaptcha_checkbox", "hcaptcha_image"}


def _click_submit(page) -> None:
    # Prefer an explicit hook (tests), else a best-effort submit button.
    if hasattr(page, "click_submit"):
        page.click_submit()
    else:
        page.get_by_role("button", name="Submit").click()


def run_once(page, profile, resume_path, meta, human, do_submit, on_link=None) -> dict:
    form = snapshot_form(page)
    gate = classify_gate(page)
    decisions = map_fields(form, profile, resume_path)
    apply_decisions(page, decisions)

    remote_solve_attempted = False
    gate_after_solve = None
    if HANDLERS.get(gate, "escalate") == "escalate" and gate in INTERACTIVE_GATES:
        remote_solve_attempted = True
        if human.remote_solve(page, gate, on_link or (lambda u: None)):
            gate = classify_gate(page)       # re-read after the human solved it
            gate_after_solve = gate

    card = render_card(meta["company"], meta["role"], meta["portal"], decisions, gate)
    gate_clear = HANDLERS.get(gate, "escalate") == "proceed"
    approved = submitted = False
    if do_submit and gate_clear:
        approved = human.approve(card)
        if approved:
            _click_submit(page)
            submitted = True

    return {"gate": gate, "card": card, "approved": approved, "submitted": submitted,
            "decisions": decisions, "remote_solve_attempted": remote_solve_attempted,
            "gate_after_solve": gate_after_solve}


def main() -> None:
    from .config.settings import load_settings
    from .browser.runner import launch, close
    from .browser.gate_probe import is_cleared
    from .memory.factual_core import load_profile
    from .integrations.live_view.tailscale import detect_host
    from .integrations.live_view.session import RemoteSolveSession
    from .integrations.telegram.client import TelegramClient
    from .integrations.telegram.approver import TelegramApprover

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

    on_link = None
    if settings.telegram_bot_token and settings.telegram_chat_id:
        telegram_client = TelegramClient(settings.telegram_bot_token, settings.telegram_chat_id)
        approver = TelegramApprover(telegram_client)
        on_link = lambda url: telegram_client.send_message(url)
    else:
        approver = CliApprover()

    remote_solve_factory = None
    host = detect_host(settings)
    if host is not None:
        remote_solve_factory = lambda page: RemoteSolveSession(
            page, host, settings.remote_solve_port, settings.remote_solve_ttl,
            settings.remote_solve_allow_public, is_cleared)

    human = HumanLoop(approver, remote_solve_factory=remote_solve_factory)

    pw, context, page = launch(settings)
    try:
        page.goto(args.url)
        meta = {"company": args.company, "role": args.role, "portal": args.url}
        out = run_once(page, profile, args.resume, meta, human, args.submit, on_link=on_link)
        print(out["card"])
        print(f"\n[gate={out['gate']}] submitted={out['submitted']}")
    finally:
        close(pw, context)


if __name__ == "__main__":
    main()
