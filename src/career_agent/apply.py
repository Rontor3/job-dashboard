"""Entrypoint: walk a full multi-page application from a target URL."""
from __future__ import annotations

import argparse
import hashlib


def _run_graph(cfg: dict, url: str, job_id, do_submit: bool, autonomous: bool,
               max_steps: int, human, jd_text: str | None = None) -> dict:
    """Drive the LangGraph graph; handles interrupt/resume cycle for human gates."""
    print("[engine] LangGraph", flush=True)
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command
    from .orchestrator.graph import build_graph, initial_state

    checkpointer = InMemorySaver()
    app = build_graph(checkpointer=checkpointer)
    state = initial_state(url, job_id=job_id, jd_text=jd_text, do_submit=do_submit,
                          autonomous=autonomous, max_steps=max_steps)
    result = app.invoke(state, cfg)

    _last_pending_sig = None
    _stuck_count = 0
    while True:
        snapshot = app.get_state(cfg)
        if not snapshot.next:
            break
        pending = snapshot.values.get("pending_human", [])
        if not pending:
            break
        # Guard: if the same fields are stuck in human_gate with no progress,
        # break rather than looping forever (e.g. SR vendor-search-handler).
        _sig = frozenset(d.get("ref") for d in pending)
        if _sig == _last_pending_sig:
            _stuck_count += 1
            if _stuck_count >= 2:
                print(f"[graph] same {len(pending)} field(s) stuck in human_gate — stopping", flush=True)
                break
        else:
            _stuck_count = 0
        _last_pending_sig = _sig
        from .browser.form_model import Field
        fields = [Field(**d) for d in pending]
        answers: dict = {}
        # Retry judgment before Telegram — cap resets each call so stragglers
        # that hit the per-screen cap in fill_node get a second chance here.
        _jfn = cfg["configurable"].get("judge_fn")
        if _jfn and fields:
            try:
                _auto, fields, _ = _jfn(fields)
                for d in _auto:
                    answers[d.ref] = d.value
                if _auto:
                    print(f"[judge-retry] auto-answered {len(_auto)} straggler(s)", flush=True)
            except Exception:
                pass
        if fields:
            print(f"[telegram] sending {len(fields)} field question(s) — waiting for reply...", flush=True)
            answers.update(human.collect(fields))
            print(f"[telegram] received {len(answers)} answer(s)", flush=True)
        result = app.invoke(Command(resume=answers), cfg)

    return result or {}


def main() -> None:
    import sqlite3
    from .config.settings import load_settings
    from .browser.runner import launch, close
    from .orchestrator.browser_deps import BrowserDeps
    from .orchestrator.step_engine import walk
    from .memory.candidate_profile import load_candidate_profile
    from .integrations.approver import CliApprover, CliCollector, NullCollector, AutoDenyApprover
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
    ap.add_argument("--no-llm", action="store_true",
                    help="skip judgment + combobox LLM tiers (fast dry-run)")
    ap.add_argument("--no-telegram", action="store_true",
                    help="force CLI collector (stdin) even if Telegram is configured")
    ap.add_argument("--screenshot", default=None,
                    help="save a full-page screenshot to this path after fill")
    ap.add_argument("--no-langgraph", action="store_true",
                    help="fall back to legacy walk() loop (escape hatch while graph is new)")
    ap.add_argument("--thread-id", default=None,
                    help="LangGraph thread id for resume (default: hash of URL)")
    ap.add_argument("--cdp-url", default=None, metavar="URL",
                    help="attach to existing Chrome via CDP (e.g. http://localhost:9222); "
                         "uses real browser session instead of launching headless Playwright")
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
            from pathlib import Path
            _fallback = Path(args.db).parent / "resumes" / "resume.pdf"
            if _fallback.exists():
                resume_pdf = str(_fallback)
                print(f"[resume] render failed ({type(e).__name__}), using pre-built {resume_pdf}")
            else:
                print(f"[warn] résumé render unavailable ({type(e).__name__}: {e}); "
                      "file fields will escalate")
                resume_pdf = None

    # Judgment tier (Phase E): answer free-text/enum fields the rules escalate,
    # grounded in the JD (--job-id) + profile, via local qwen. Degrades to None
    # (rules + human only) if unavailable. --no-llm skips both for fast dry-runs.
    judge_fn = None
    option_matcher = None
    if not args.no_llm:
        try:
            from .orchestrator.judgment import JudgmentContext, profile_to_text, judge
            from .browser.ats_lookup import lookup as _ats_lookup
            from job_dashboard.db import get_job
            from job_dashboard.letter.draft import make_default_llm
            job = (get_job(conn, args.job_id) if args.job_id else None) or \
                {"title": "", "company": "", "description": ""}
            llm = make_default_llm()
            _vendor = _ats_lookup(args.url)
            _ats_notes = ""
            if _vendor:
                _ats_notes = _vendor.get("notes", "")
                hints = _vendor.get("fix_hints") or []
                if hints:
                    _ats_notes += " | Known fixes: " + "; ".join(hints[:3])
            ctx = JudgmentContext(job=job, profile_text=profile_to_text(profile),
                                  resume_text=job.get("description", ""),
                                  ats_notes=_ats_notes)
            judge_fn = lambda needs: judge(needs, ctx, llm, cap=20)
        except Exception as e:
            print(f"[warn] judgment tier unavailable ({type(e).__name__}: {e})")

        # Combobox value->option matcher (rung 3): maps our answer to a React
        # dropdown's live option (e.g. Male->Man) when exact/word match misses.
        try:
            from .orchestrator.judgment import match_value_to_option
            from job_dashboard.letter.draft import make_default_llm
            _mllm = make_default_llm()
            option_matcher = lambda label, value, options: match_value_to_option(
                label, value, options, _mllm)
        except Exception as e:
            print(f"[warn] combobox matcher unavailable ({type(e).__name__}: {e})")

    # Learning loop (Phase D): reuse answers the human typed on past forms
    # before escalating again; record new ones. Same jobs.db, no new store.
    from .memory.learned_answers import AnswerMemory
    learn = AnswerMemory(conn)

    memory_router = None
    try:
        from pathlib import Path as _Path
        from .memory.exact_tech import ExactTechVault
        from .memory.semantic_behavior import SemanticBehaviorVault
        from .routers.memory_router import MemoryRouter
        _semantic_dir = str(_Path(args.db).parent / "semantic_behavior")
        memory_router = MemoryRouter(
            profile=contact,
            exact_tech=ExactTechVault(),
            semantic=SemanticBehaviorVault(persist_dir=_semantic_dir),
            answer_memory=learn,
        )
    except Exception as _me:
        print(f"[warn] memory router unavailable ({type(_me).__name__}: {_me})")

    settings = load_settings()

    # Telegram wiring: upgrade approver/collector and enable remote captcha solve
    # when TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID are set; otherwise fall back to CLI.
    on_link = None
    remote_solve_factory = None
    if not args.no_telegram and settings.telegram_bot_token and settings.telegram_chat_id:
        from .integrations.telegram.client import TelegramClient
        from .integrations.telegram.approver import TelegramApprover
        from .integrations.telegram.collector import TelegramCollector
        from .integrations.live_view.tailscale import detect_host
        from .integrations.live_view.session import RemoteSolveSession
        from .browser.gate_probe import is_cleared_for
        _tg = TelegramClient(settings.telegram_bot_token, settings.telegram_chat_id)
        approver = TelegramApprover(_tg)
        collector = TelegramCollector(_tg)

        def on_link(url):
            msg = "\U0001F9E9 Captcha — open the live view and solve it:\n" + url
            mid = _tg.send_message(msg)
            print(f"[live-view] {url}", flush=True)
            print(f"[telegram] captcha link sent (message_id={mid})", flush=True)
            return mid

        host = detect_host(settings)
        if host is not None:
            remote_solve_factory = lambda page, gate: RemoteSolveSession(
                page, host, settings.remote_solve_port, settings.remote_solve_ttl,
                settings.remote_solve_allow_public, is_cleared_for(gate), captcha_kind=gate)
            print(f"[remote-solve] enabled via Telegram — host={host}")
        else:
            print("[remote-solve] DISABLED — Tailscale host not detected")
    else:
        if args.no_telegram:
            approver = AutoDenyApprover()
            collector = NullCollector()
        else:
            approver = CliApprover()
            collector = CliCollector()

    human = HumanLoop(approver, remote_solve_factory=remote_solve_factory,
                      deadline_s=settings.remote_solve_ttl, collector=collector)
    from .browser.page_prep import prepare, classify_entry, enter_application, email_auth, is_application_form
    _cdp_url = args.cdp_url or settings.cdp_url
    pw, context, page, _cdp_browser = launch(settings, cdp_url=_cdp_url)
    try:
        resp = page.goto(args.url)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        # Scrape JD text from the landing page before clicking Apply Now.
        # Used only this run to ground company-specific Telegram questions.
        try:
            jd_text = (page.inner_text("body") or "")[:5000].strip() or None
        except Exception:
            jd_text = None
        if jd_text and hasattr(collector, "jd_text"):
            collector.jd_text = jd_text
        # Update judgment ctx with scraped JD so qwen has company context
        if jd_text and 'ctx' in dir():
            try:
                ctx.resume_text = jd_text[:2000]
            except Exception:
                pass
        prepare(page)                          # clear cookie/idle overlays
        kind = classify_entry(page, status=resp.status if resp else None)
        if kind == "closed":                   # expired / removed / 404 shell -> skip
            print("[skip] this posting is closed or no longer available.")
            return
        # kind=="none" = clear JD page; kind=="form" can false-positive on pages
        # that have search/filter inputs but no real applicant fields (e.g. Phenom).
        if kind == "none" or (kind == "form" and not is_application_form(page)):
            # Close stale ATS tabs from previous runs so pages[-1] after Apply
            # click reliably points to the new (fresh-session) login tab.
            _ATS_HOSTS = ("taleo.net", "greenhouse.io", "icims.com", "workday.com",
                          "darwinbox.in", "successfactors.com", "ashbyhq.com",
                          "lever.co", "recruitee.com", "jobvite.com")
            for _sp in list(page.context.pages):
                if _sp is not page and any(h in (_sp.url or "") for h in _ATS_HOSTS):
                    try: _sp.close()
                    except Exception: pass
            enter_application(page)
            page = page.context.pages[-1]      # adopt a new tab if one opened
            prepare(page); kind = classify_entry(page)
        if kind == "closed":
            print("[skip] this posting is closed or no longer available.")
            return
        # OTP reader shared by email_auth (ZF/Phenom) and otp_email gate (SAP SF).
        # Prefers Gmail API (fully automated); falls back to file drop.
        import time as _time, pathlib as _pl
        _otp_path = _pl.Path("/tmp/career_agent_otp.txt")

        def _file_otp_reader(path=_otp_path, timeout=300):
            path.unlink(missing_ok=True)
            print(f"[otp] Waiting for OTP/magic-link — write it to {path}")
            for _ in range(timeout // 2):
                _time.sleep(2)
                if path.exists():
                    val = path.read_text().strip()
                    if val:
                        path.unlink(missing_ok=True)
                        return val
            return None

        try:
            from .integrations.gmail_otp import poll_otp as _gmail_poll, available as _gmail_ok
            if _gmail_ok():
                def _file_otp_reader(timeout=300):  # noqa: F811
                    return _gmail_poll(timeout_s=timeout)
            else:
                print("[otp] Gmail token not found — using file reader (/tmp/career_agent_otp.txt)")
        except ImportError:
            pass  # google client libs not installed yet

        from .browser.credential_provider import provide as _provide
        from .browser.page_prep import clear_auth_wall
        _job_url = args.url
        _profile_email = contact.get("email", "")
        _provide_url = lambda pg, gate, site: _provide(
            pg, gate, site, original_url=_job_url, email=_profile_email)

        if kind == "password":
            print("[password] attempting credential provider...")
            clear_auth_wall(page, credential_provider=_provide_url)
            page = page.context.pages[-1]  # adopt new tab if guest-apply opened one
            kind = classify_entry(page)
            # After Darwinbox registration the provider navigates back to the JD
            # page; re-enter the application so walk() lands on the form.
            if kind in ("none", "form") and not is_application_form(page):
                enter_application(page)
                page = page.context.pages[-1]
                prepare(page); kind = classify_entry(page)
            # Registration+application on one page (e.g. SAP SuccessFactors): the
            # credential provider fills the auth fields; walk() fills the rest.
            if kind == "password" and is_application_form(page):
                print("[password] combined registration+application form — walk() handles remainder")
                kind = "form"
            elif kind == "password":
                print("[stop] credential provider could not clear the login wall. "
                      "Log in manually in the open browser, then re-run.")
                print({"url": args.url, "stopped_reason": "auth_wall",
                       "filled_count": 0, "escalated_count": 0}, flush=True)
                return
        if kind == "email_auth":               # passwordless email->OTP/magic-link->form
            email_auth(page, contact.get("email", ""), otp_reader=_file_otp_reader, on_captcha=None)
        deps = BrowserDeps(option_matcher=option_matcher)
        # Register live context for mcp_server tools (no-op if mcp package absent)
        try:
            from . import mcp_server as _mcp
            _mcp.set_session(page=page, deps=deps, memory_router=memory_router,
                             human_loop=human, profile=profile)
        except ImportError:
            pass
        # Prefer stored JD from DB (full description) over page body scrape (3 kB cap).
        try:
            _db_jd = job.get("description") or jd_text  # `job` set if --job-id + LLM tier
        except NameError:
            _db_jd = jd_text  # --no-llm path: job not loaded; fall back to page scrape

        tid = args.thread_id or hashlib.sha1(args.url.encode()).hexdigest()[:16]
        graph_cfg = {"configurable": {
            "thread_id": tid, "page": page, "profile": profile, "deps": deps,
            "human": human, "collector": collector, "resume_pdf": resume_pdf,
            "judge_fn": judge_fn, "prep_fn": prepare, "learn": learn,
            "on_link": on_link, "memory_router": memory_router,
            "judgment_ctx": ctx if judge_fn else None,  # so classify_node can update resume_text
        }}

        def _walk():
            print("[engine] walk()", flush=True)
            return walk(page, profile, human, deps,
                        max_steps=args.max_steps, do_submit=args.submit,
                        autonomous=args.autonomous, resume_pdf=resume_pdf,
                        judge_fn=judge_fn, prep_fn=prepare, learn=learn,
                        on_link=on_link, cred_provider=_provide_url)

        if not args.no_langgraph:
            try:
                out = _run_graph(graph_cfg, args.url, args.job_id,
                                 args.submit, args.autonomous, args.max_steps, human,
                                 jd_text=_db_jd)
            except Exception as _ge:
                print(f"[graph] failed ({_ge}), falling back to walk()", flush=True)
                out = _walk()
        else:
            print("[engine] walk() (--no-langgraph)", flush=True)
            out = _walk()
        ss_path = args.screenshot or "/tmp/career_agent_fill_result.png"
        try:
            page.screenshot(path=ss_path, full_page=True)
            print(f"[screenshot] {ss_path}", flush=True)
        except Exception as _se:
            print(f"[screenshot] failed: {_se}", flush=True)
        _write_run_log(conn, args.url, args.job_id, out)
        _append_pending_memory(args.db, args.url, args.job_id, out)
        # Update portal state so bulk runner has accurate domain counts/cooldowns
        try:
            from .reliability.rate_limiter import RateLimiter, map_outcome, domain_key
            RateLimiter().record(domain_key(args.url),
                                 map_outcome(out.get("stopped_reason", "error")))
        except Exception:
            pass
        print(out)
    finally:
        close(pw, context, page=page, cdp_browser=_cdp_browser)


def _append_pending_memory(db_path: str, url: str, job_id, result: dict) -> None:
    """Append a structured run summary to data/pending_memory_updates.md.

    The next Claude session reads this file, promotes entries to the right
    memory files (phase3b-findings, user-answers, status), then clears it.
    """
    import datetime as _dt
    from pathlib import Path as _P
    pending = result.get("pending_human") or []
    decisions = result.get("decisions") or []
    out_path = _P(db_path).parent / "pending_memory_updates.md"
    ts = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"\n## Run {ts}",
        f"- URL: {url}",
        f"- job_id: {job_id}",
        f"- stopped_reason: {result.get('stopped_reason')}",
        f"- filled: {len(decisions)}  escalated: {len(pending)}",
        f"- submitted: {bool(result.get('submitted'))}",
    ]
    if pending:
        lines.append("- escalated_fields:")
        for f in pending:
            label   = f.get("label") or f.get("ref", "?")
            purpose = f.get("purpose") or "unknown"
            lines.append(f"    - {label!r}  (purpose={purpose})")
    lines.append("")   # trailing blank line
    try:
        with open(out_path, "a") as fh:
            fh.write("\n".join(lines) + "\n")
        print(f"[memory] pending update written → {out_path}", flush=True)
    except Exception as _e:
        print(f"[memory] pending update failed ({_e})", flush=True)


def _write_run_log(conn, url: str, job_id, result: dict) -> None:
    """Append one row to run_log in jobs.db after every run."""
    import json as _json
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS run_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT,
                url         TEXT,
                job_id      INTEGER,
                stopped_reason TEXT,
                filled      INTEGER,
                escalated   INTEGER,
                submitted   INTEGER,
                result_json TEXT
            )
        """)
        decisions = result.get("decisions") or []
        pending   = result.get("pending_human") or []
        import datetime as _dt
        conn.execute(
            "INSERT INTO run_log(ts, url, job_id, stopped_reason, filled, escalated, submitted, result_json)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (_dt.datetime.utcnow().isoformat(), url, job_id,
             result.get("stopped_reason"),
             len(decisions),
             len(pending),
             int(bool(result.get("submitted"))),
             _json.dumps({"escalated_labels": [d.get("label") for d in pending]})),
        )
        conn.commit()
        print(f"[run_log] recorded — filled={len(decisions)} escalated={len(pending)}", flush=True)
    except Exception as _e:
        print(f"[run_log] failed to write ({_e})", flush=True)


if __name__ == "__main__":
    main()
