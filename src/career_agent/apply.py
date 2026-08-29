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
    ap.add_argument("--resume-pdf", default=None,
                    help="PDF to attach; default renders the chosen --resume-version")
    ap.add_argument("--job-id", type=int, default=None,
                    help="jobs-table id whose JD grounds judgment-tier free-text answers")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    contact = get_application_profile(conn) or {}
    profile = load_candidate_profile(conn, args.resume_version, contact=contact)

    resume_pdf = args.resume_pdf
    if resume_pdf is None:
        try:
            from pathlib import Path
            from job_dashboard.db import get_resume_layout
            from job_dashboard.resume.engine import render_layout_pdf
            from job_dashboard.resume.render import render_pdf
            from job_dashboard.resume.segments import load_segments
            rec = get_resume_layout(conn, args.resume_version)
            out_dir = Path(args.db).parent / "resumes"
            out_dir.mkdir(parents=True, exist_ok=True)
            res = render_layout_pdf(rec["layout"], segments=load_segments(),
                                    render_pdf=render_pdf, out_dir=out_dir)
            resume_pdf = str(res["pdf_path"])
        except Exception as e:
            print(f"[warn] résumé render unavailable ({type(e).__name__}: {e}); "
                  "file fields will escalate")
            resume_pdf = None

    # Judgment tier (Phase E): answer free-text/enum fields the rules escalate,
    # grounded in the JD (--job-id) + profile, via local qwen. Degrades to None
    # (rules + human only) if unavailable.
    judge_fn = None
    try:
        from .orchestrator.judgment import JudgmentContext, profile_to_text, judge
        from job_dashboard.db import get_job
        from job_dashboard.letter.draft import make_default_llm
        job = (get_job(conn, args.job_id) if args.job_id else None) or \
            {"title": "", "company": "", "description": ""}
        llm = make_default_llm()
        ctx = JudgmentContext(job=job, profile_text=profile_to_text(profile),
                              resume_text=job.get("description", ""))
        judge_fn = lambda needs: judge(needs, ctx, llm, cap=6)
    except Exception as e:
        print(f"[warn] judgment tier unavailable ({type(e).__name__}: {e})")
        judge_fn = None

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
                   max_steps=args.max_steps, do_submit=args.submit,
                   autonomous=args.autonomous, resume_pdf=resume_pdf, judge_fn=judge_fn)
        print(out)
    finally:
        close(pw, context)


if __name__ == "__main__":
    main()
