"""Agent-driven apply runs: the live page per job and what each tool does with it (spec 2026-10-11).

One `ApplySession` per job holds the open tab and the run's memory (fields on screen, decisions so far). Every page
step runs on the browser thread (session_actor); the run's state lives in `apply_run` (run_store) so the queue, the
Inbox and a resumed run all read the same thing. Walls the agent never crosses end the run as `skipped` with the
reason: a captcha (never solved), a sign-in / sign-up wall, a closed posting."""
from __future__ import annotations

import dataclasses
import json
import os
import threading
from dataclasses import dataclass, field

from job_dashboard import notifications, paths, qa_store
from job_dashboard.apply import run_store
from job_dashboard.apply import session_steps as steps
from job_dashboard.db import init_db

# Walls: the run ends here, with the reason, and the queue moves on.
SKIP_ON = {"captcha", "closed", "account_needed", "logged_out", "unreachable", "one_click_entry", "no_entry"}
_WHY = {"captcha": "hit a captcha (the agent never solves those)", "closed": "the posting is closed",
        "account_needed": "the site wants an account or a sign-in", "logged_out": "you're logged out of the board",
        "unreachable": "the page did not load", "one_click_entry": "the board applies on one click",
        "no_entry": "no Apply control on the page", "needs_answers": "has questions only you can answer",
        "review": "is filled; an answer the agent wrote needs your review before submit",
        "sensitive_field": "needs bank or ID details only you can enter",
        "submit_unconfirmed": "was submitted but the site didn't confirm it", "max_steps": "took too many steps"}
_STABLE_CITE = {"profile", "resume", "qbank", "ingredients", "jd", "option", "human"}
_SUGGEST_LABEL = {"qbank_likely"}           # a LIKELY bank match the agent accepts is still not the user's words


@dataclass
class ApplySession:
    job_id: int
    url: str
    ctx: dict
    qa: object = None
    conn: object = None                                 # the run's own connection (the recorder and the bank use it)
    page: object = None
    board: dict | None = None
    cap: object = None
    kind: str = ""
    step: int = 0
    tab_target_id: str | None = None
    fields: dict = field(default_factory=dict)          # short id -> Field on the current page
    suggest: dict = field(default_factory=dict)         # short id -> FillDecision from the ladder
    decisions: dict = field(default_factory=dict)       # ref -> FillDecision written so far
    agent_written: list = field(default_factory=list)   # labels of answers the agent composed
    scrolled: set = field(default_factory=set)          # (url, step) pages already scrolled through once
    tabs: list = field(default_factory=list)            # every tab this run worked in (Apply may open a new one)


class ApplySessionError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


class ApplySessions:
    def __init__(self, db_path, actor, ctx_factory=None, notify_push=None):
        self.db_path, self.actor = str(db_path), actor
        self.ctx_factory = ctx_factory or build_ctx
        self.notify_push = notify_push if notify_push is not None else _telegram_push
        self.sessions: dict[int, ApplySession] = {}
        self._lock_fd: int | None = None
        self._active: int | None = None
        self._mu = threading.Lock()

    # ── helpers ───────────────────────────────────────────────────────────────────────────────────────────────
    def _conn(self):
        return init_db(self.db_path)

    def _session(self, job_id: int) -> ApplySession:
        s = self.sessions.get(job_id)
        if s is None or s.page is None:
            raise ApplySessionError(409, "no open apply run for this job: call apply_start first")
        return s

    def _run(self, job_id: int, fn):
        """fn(session, conn) on the browser thread; a StepError becomes a 422 the agent can read."""
        s = self._session(job_id)
        def go(_context):
            conn = self._conn()
            try:
                return fn(s, conn)
            finally:
                if s.page is not None and s.page not in s.tabs:
                    s.tabs.append(s.page)
                conn.close()
        try:
            return self.actor.call(go)
        except steps.StepError as e:
            raise ApplySessionError(422, str(e))

    def _acquire(self, job_id: int) -> None:
        """The one-Chrome single-flight lock the script engine also takes (AgentRunState)."""
        with self._mu:
            if self._active == job_id:
                return
            if self._active is not None:
                raise ApplySessionError(409, f"another apply run (job {self._active}) is using the browser")
            if self._lock_fd is None and os.name == "posix":
                import fcntl
                paths.STATE.mkdir(parents=True, exist_ok=True)
                fd = os.open(paths.STATE / "agent_run.lock", os.O_CREAT | os.O_RDWR)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(fd)
                    raise ApplySessionError(409, "a script apply run is using the browser")
                self._lock_fd = fd
            self._active = job_id

    def _release(self, job_id: int) -> None:
        with self._mu:
            if self._active != job_id:
                return
            self._active = None
            if self._lock_fd is not None:
                import fcntl
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
                self._lock_fd = None

    def _what(self, conn, job_id: int) -> str:
        r = conn.execute("SELECT title, company FROM jobs WHERE id=?", (job_id,)).fetchone()
        return f"{r[0]} at {r[1]}" if r else f"job #{job_id}"

    def _close_tab(self, s: ApplySession) -> None:
        try:
            if s.conn is not None:
                s.conn.close()
        except Exception:
            pass
        s.conn = None
        steps._close_capture(s.cap)
        s.cap = None
        for tab in dict.fromkeys([*s.tabs, s.page]):      # the listing tab too, when the form opened in another
            try:
                if tab is not None:
                    tab.close()
            except Exception:
                pass
        s.page, s.tabs = None, []

    # ── lifecycle ─────────────────────────────────────────────────────────────────────────────────────────────
    def status(self, job_id: int) -> dict:
        conn = self._conn()
        try:
            row = run_store.get(conn, job_id) or {"job_id": job_id, "state": None}
            row["priority"] = run_store.priority(conn, job_id)
            return row
        finally:
            conn.close()

    def start(self, job_id: int, agent_session: str | None = None) -> dict:
        live = self.sessions.get(job_id)
        if live is not None and live.page is not None:
            self._acquire(job_id)                       # a paused run whose tab is still open: carry on there
            conn = self._conn()
            try:
                run_store.save(conn, job_id, state="running", reason=None, agent_session=agent_session)
                return {"resumed": True, "step": live.step, "url": live.page.url,
                        "priority": run_store.priority(conn, job_id),
                        "note": "the tab is where the run paused; call apply_snapshot"}
            finally:
                conn.close()
        conn = self._conn()
        try:
            job = conn.execute("SELECT job_url, apply_kind, apply_url FROM jobs WHERE id=?", (job_id,)).fetchone()
            if job is None:
                raise ApplySessionError(404, "job not found")
            from job_dashboard.apply.queue_runner import job_target
            url = job_target({"job_url": job[0], "apply_kind": job[1], "apply_url": job[2]})
            if not url:
                raise ApplySessionError(422, "this job has no link to apply on")
            prio = run_store.priority(conn, job_id)
        finally:
            conn.close()
        self._acquire(job_id)
        try:
            def go(context):
                c = self._conn()
                try:
                    import sqlite3
                    run_conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    ctx, qa = self.ctx_factory(run_conn, job_id)
                    s = ApplySession(job_id, url, ctx, qa, run_conn)
                    self.sessions[job_id] = s
                    run_store.save(c, job_id, state="running", reason=None, detail=None, step=0, url=url,
                                   run_key=getattr(qa, "run_key", None), agent_session=agent_session, priority=prio,
                                   tab_open=1)
                    out = steps.start(s, context)
                    s.tabs.append(s.page)
                    run_store.save(c, job_id, tab_target_id=s.tab_target_id, url=getattr(s.page, "url", url))
                    return out
                finally:
                    c.close()
            out = self.actor.call(go)
        except Exception:
            self._release(job_id)
            raise
        out["priority"] = prio
        return self._skip_if_walled(job_id, out)

    def _skip_if_walled(self, job_id: int, out: dict) -> dict:
        if out.get("blocked") in SKIP_ON:
            self.skip(job_id, out["blocked"], out.get("detail") or "")
            return {**out, "skipped": True, "next": "the run is over; say why in one line and stop"}
        return out

    def reach(self, job_id: int) -> dict:
        def go(s, conn):
            out = steps.reach(s)
            # the tab the form is in now: Resume, Show tab and the submit watcher look it up by this id
            run_store.save(conn, job_id, tab_target_id=s.tab_target_id, url=s.page.url)
            return out
        return self._skip_if_walled(job_id, self._run(job_id, go))

    def snapshot(self, job_id: int) -> dict:
        out = self._run(job_id, lambda s, c: steps.snapshot(s))
        if out.get("submitted_confirmed"):
            return self._finish_submitted(job_id, "the board confirmed it")
        return self._skip_if_walled(job_id, out)

    def fill(self, job_id: int, answers: list[dict], accept_suggestions: bool = False) -> dict:
        def go(s, conn):
            decisions, rejected = [], []
            given = {a.get("id") for a in answers}
            if accept_suggestions:
                decisions += [(d, None, d.source in _SUGGEST_LABEL) for fid, d in s.suggest.items() if fid not in given]
            for a in answers:
                f = s.fields.get(a.get("id"))
                if f is None:
                    rejected.append({"id": a.get("id"), "why": "no such field on this page: take a new snapshot"})
                    continue
                if steps.is_sensitive(f):
                    rejected.append({"id": a["id"], "why": "bank / ID detail: never filled by the agent"})
                    continue
                source, cite = (a.get("source") or "").strip(), a.get("citation")
                if source != "agent" and not (source in _STABLE_CITE and cite):
                    rejected.append({"id": a["id"], "why": "cite where the value came from "
                                     f"(source one of {sorted(_STABLE_CITE)} + citation), or use source=agent"})
                    continue
                try:
                    decisions.append((steps.decision_for(s, f, a.get("value"), source), cite, source == "agent"))
                except steps.StepError as e:
                    rejected.append({"id": a["id"], "why": str(e)})
            blocked = set(steps.behind_dialog(s, [d.ref for d, _, _ in decisions])) if decisions else set()
            if blocked:
                for d, _, _ in decisions:
                    if d.ref in blocked:
                        rejected.append({"id": next((k for k, f in s.fields.items() if f.ref == d.ref), d.ref),
                                         "why": "a dialog is open over the page: answer it first (apply_dialog)"})
                decisions = [x for x in decisions if x[0].ref not in blocked]
            if decisions:
                steps.put(s, [d for d, _, _ in decisions])
            for d, cite, written in decisions:
                s.decisions[d.ref] = d
                if s.qa:
                    s.qa.decision(d)
                    if written or cite:
                        s.qa.agent_answer(d, cite, written)
                if written and d.label not in s.agent_written:
                    s.agent_written.append(d.label)
            lost = steps.did_not_stick(s, [d for d, _, _ in decisions])
            after = steps.snapshot(s)
            required_empty = [{"id": r["id"], "label": r["label"]} for r in after.get("fields", [])
                              if r["required"] and not r.get("value") and r["kind"] not in ("file", "checkbox", "radio_group")
                              and r["label"] not in {d.label for d, _, _ in decisions}]
            return {"applied": len(decisions), "rejected": rejected, "did_not_stick": lost,
                    "required_empty": required_empty, "page": after}
        return self._run(job_id, go)

    def advance(self, job_id: int) -> dict:
        def go(s, conn):
            out = steps.advance(s)
            run_store.save(conn, job_id, step=s.step, url=s.page.url)
            return out
        return self._run(job_id, go)

    def submit(self, job_id: int) -> dict:
        from job_dashboard import autonomy
        def go(s, conn):
            hold = run_store.priority(conn, job_id) in run_store.hold_priorities(conn)
            ds = [dataclasses.asdict(d) for d in s.decisions.values()]
            verdict = autonomy.autosubmit_policy(conn, s.page.url, getattr(s.qa, "run_key", ""), ds,
                                                 agent_mode=True, hold=hold)
            _save_eligibility(job_id, verdict)
            if not verdict["allow"]:
                return {"held": True, "reasons": verdict["reasons"],
                        "next": "do not retry: call apply_pause with reason 'review' and these reasons"}
            from career_agent.browser.form_values import read_form_values
            try:
                values = read_form_values(s.page)
            except Exception:
                values = {}
            ok, why = steps.submit_click(s)
            if ok:
                autonomy.record_submission(conn, job_id, getattr(s.qa, "run_key", ""),
                                           {autonomy.key(k): v for k, v in values.items()}, "auto", s.page.url)
            return {"confirmed": ok, "why": why}
        out = self._run(job_id, go)
        if out.get("held"):
            return out
        if out["confirmed"]:
            return self._finish_submitted(job_id, out["why"])
        self.pause(job_id, "submit_unconfirmed", out["why"], [])
        return {"submitted": False, "why": out["why"], "paused": True}

    def _finish_submitted(self, job_id: int, why: str) -> dict:
        s = self.sessions.get(job_id)
        conn = self._conn()
        try:
            from job_dashboard.db import set_job_status
            run_store.save(conn, job_id, state="submitted", reason=None, detail=why, tab_open=0)
            set_job_status(conn, job_id, "applied")
            written = s.agent_written if s else []
            body = ("Answers the agent wrote itself (not your words): " + "; ".join(written)) if written else None
            notifications.safe_notify(conn, "submitted", f"Applied: {self._what(conn, job_id)}", body, level="success",
                                      job_id=job_id, source="agent", data={"agent_written": written},
                                      dedupe=f"run:{job_id}")
        finally:
            conn.close()
        if s:
            self.actor.call(lambda _c: self._close_tab(s))
        self.sessions.pop(job_id, None)
        self._release(job_id)
        return {"submitted": True, "why": why, "next": "the run is over; say so in one line and stop"}

    def pause(self, job_id: int, reason: str, detail: str, questions: list[dict]) -> dict:
        s = self.sessions.get(job_id)
        conn = self._conn()
        try:
            asked = []
            for q in questions or []:
                f = s.fields.get(q.get("id")) if s else None
                label = (f.label if f else q.get("label")) or q.get("id") or "question"
                asked.append({"label": label, "why": q.get("why", "")})
                if f is not None and s.qa:
                    s.qa.needs(f)
            closed = self._enforce_tab_cap(conn, keep=job_id)
            run_store.save(conn, job_id, state="paused", reason=reason, detail=detail,
                           tab_open=1 if s and s.page is not None else 0, step=s.step if s else 0,
                           **({"tab_target_id": s.tab_target_id} if s and s.tab_target_id else {}))
            why = _WHY.get(reason, reason.replace("_", " "))
            lines = [detail] if detail else []
            lines += [f"• {a['label']}" + (f" — {a['why']}" if a["why"] else "") for a in asked]
            written = s.agent_written if s else []
            if written:
                lines.append("Written by the agent, not your words: " + "; ".join(written))
            what = self._what(conn, job_id)
            notifications.safe_notify(conn, "parked", f"{what} {why}", "\n".join(lines) or None, level="action",
                                      job_id=job_id, source="agent", dedupe=f"run:{job_id}",
                                      data={"reason": reason, "live": True, "tab_open": bool(s and s.page),
                                            "questions": asked, "agent_written": written,
                                            "tab_target_id": s.tab_target_id if s else None})
        finally:
            conn.close()
        self.notify_push(f"⏸ {what} {why}\n" + "\n".join(lines))
        self._release(job_id)
        return {"paused": True, "tab_open": bool(s and s.page), "closed_oldest": closed,
                "next": "the run is paused; tell the user in one line what is needed and stop"}

    def _enforce_tab_cap(self, conn, keep: int) -> list[int]:
        try:
            cap = max(1, int(qa_store.get_setting(conn, "apply_max_open_tabs")))
        except (KeyError, ValueError):
            cap = 5
        others = [r for r in run_store.open_paused(conn) if r["job_id"] != keep]
        closed = []
        while len(others) + 1 > cap:
            old = others.pop(0)
            s = self.sessions.pop(old["job_id"], None)
            if s:
                self.actor.call(lambda _c, s=s: self._close_tab(s))
            run_store.save(conn, old["job_id"], tab_open=0)
            closed.append(old["job_id"])
        return closed

    def skip(self, job_id: int, reason: str, detail: str = "") -> dict:
        if job_id not in self.sessions:
            conn = self._conn()
            try:
                row = run_store.get(conn, job_id)
            finally:
                conn.close()
            if row and row["state"] == "skipped":
                return {"skipped": True, "reason": row["reason"], "note": "already skipped; the run is over"}
        s = self.sessions.pop(job_id, None)
        if s:
            self.actor.call(lambda _c: self._close_tab(s))
        conn = self._conn()
        try:
            run_store.save(conn, job_id, state="skipped", reason=reason, detail=detail, tab_open=0)
            why = _WHY.get(reason, reason.replace("_", " "))
            notifications.safe_notify(conn, "failed", f"Skipped: {self._what(conn, job_id)}", f"It {why}. {detail}".strip(),
                                      level="warning", job_id=job_id, source="agent", data={"reason": reason},
                                      dedupe=f"run:{job_id}")
        finally:
            conn.close()
        self._release(job_id)
        return {"skipped": True, "reason": reason}

    def fail(self, job_id: int, detail: str) -> None:
        """The run ended without a verdict (timed out, the agent stopped): leave the tab, say so."""
        if job_id in self.sessions:
            self.pause(job_id, "error", detail, [])

    def dialog(self, job_id: int, button: str) -> dict:
        """Press one button of the dialog over the page; the page after it."""
        def go(s, conn):
            steps.press_dialog(s, button)
            return steps.snapshot(s)
        out = self._run(job_id, go)
        return self._skip_if_walled(job_id, {"pressed": button, "page": out} if not out.get("blocked") else out)

    def text(self, job_id: int) -> dict:
        return self._run(job_id, lambda s, c: {"url": s.page.url, "text": steps.page_text(s)})


def _save_eligibility(job_id: int, verdict: dict) -> None:
    try:
        d = paths.DATA_DIR / "agent_runs" / str(job_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "eligibility.json").write_text(json.dumps(verdict, default=str))
    except Exception:
        pass


def _telegram_push(text: str) -> None:
    """A ping on Telegram when it is set up; the Inbox card is the record either way."""
    try:
        from career_agent.config.settings import load_settings
        st = load_settings()
        if st.telegram_bot_token and st.telegram_chat_id:
            from career_agent.integrations.telegram.client import TelegramClient
            TelegramClient(st.telegram_bot_token, st.telegram_chat_id).send_message(text[:3500])
    except Exception as e:
        print(f"[apply-session] telegram ping skipped: {type(e).__name__}", flush=True)


def build_ctx(conn, job_id: int):
    """What the ladder and the filler need for this job: profile, résumé file, question bank, browser ops."""
    from career_agent.apply import supplied_resume_pdf
    from career_agent.memory.candidate_profile import load_candidate_profile
    from career_agent.orchestrator.browser_deps import BrowserDeps
    from career_agent.orchestrator.qa_recorder import QARecorder
    from job_dashboard.apply.store import get_application_profile
    from job_dashboard.db import get_job
    contact = get_application_profile(conn) or {}
    profile = load_candidate_profile(conn, "", contact=contact)
    resume = supplied_resume_pdf(upload_name=contact.get("full_name"), out_dir=paths.DATA_DIR / "resumes" / "upload")
    if resume is None and (paths.DATA_DIR / "resumes" / "resume.pdf").exists():
        resume = str(paths.DATA_DIR / "resumes" / "resume.pdf")
    job = get_job(conn, job_id) or {}
    qa = QARecorder(conn, job_id)
    learn = None
    try:
        from career_agent.memory.qbank_memory import QBankMemory
        # No model here: the agent itself judges the ambiguous questions (search_answers). Suggestions are the exact and
        # confident matches only, so a snapshot of a 60-field page takes seconds, not a model call per field.
        learn = QBankMemory(conn, llm=None, contact=contact, job=job,
                            high=qa_store.qbank_confident_min(conn) / 100)
        qa.tracer = learn.explain
    except Exception as e:
        print(f"[apply-session] question bank unavailable ({type(e).__name__}: {e})", flush=True)
    return {"profile": profile, "contact": contact, "resume_pdf": resume, "learn": learn, "job": job,
            "deps": BrowserDeps(), "job_id": job_id}, qa
