"""Entrypoint: walk a full multi-page application from a target URL."""
from __future__ import annotations

import argparse


def main() -> None:
    import sqlite3
    from .config.settings import load_settings
    from .browser.runner import launch, close
    from .orchestrator.browser_deps import BrowserDeps
    from .orchestrator.step_engine import walk
    from .memory.candidate_profile import load_candidate_profile
    from .integrations.approver import CliApprover, CliCollector
    from .integrations.human_loop import HumanLoop
    from job_dashboard.apply.store import get_application_profile

    ap = argparse.ArgumentParser(description="Career agent — multi-page application walk")
    ap.add_argument("--url", required=True)
    ap.add_argument("--db", default="data/jobs.db")
    ap.add_argument("--resume-version", default="Rakshit_Singh_draft1")
    ap.add_argument("--submit", action="store_true")
    ap.add_argument("--autonomous", action="store_true")
    ap.add_argument("--max-steps", type=int, default=15)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    contact = get_application_profile(conn) or {}
    profile = load_candidate_profile(conn, args.resume_version, contact=contact)

    settings = load_settings()
    # CLI harness: approve + collect unknowns on the terminal. remote_solve
    # stays unwired on purpose — an interactive captcha here degrades to a safe
    # stop (gate:*), never an auto-solve. Telegram wiring mirrors run.py in prod.
    human = HumanLoop(CliApprover(), collector=CliCollector())
    pw, context, page = launch(settings)
    try:
        page.goto(args.url)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        out = walk(page, profile, human, BrowserDeps(),
                   max_steps=args.max_steps, do_submit=args.submit, autonomous=args.autonomous)
        print(out)
    finally:
        close(pw, context)


if __name__ == "__main__":
    main()
