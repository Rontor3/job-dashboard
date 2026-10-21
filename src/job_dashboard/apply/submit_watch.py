"""Notice when a parked application is submitted by hand — and when a blocked tab is freed.

A run that stops for review leaves its form open in Chrome. When the human submits it there, nothing used to tell the
dashboard. The watcher keeps one row per such job (the tab, the run) and, every poll, (1) remembers what the form
holds, (2) checks whether the tab now confirms the application. On confirmation it marks the job applied, files the
submit in the history and turns the form's final values into approvals (autonomy.record_submission): what was left
as the agent filled it is approved, what you changed is reset. It only reads; it never clicks or types.

A run that stopped *inside a block* (challenge, login wall, a form it never entered) gets the same treatment with a
different ending: while the tab sits there, the poll checks whether the human cleared the block — if they did, the
job goes straight back into the apply queue (its `watch_cycles` col caps the round trips). Blocks that show nothing
to clear (`no_entry`, `stuck`, `site_refused`) are simply re-queued after a wait."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from job_dashboard import autonomy
from job_dashboard.db import init_db, set_job_status

POLL_S = 30
EMAIL_FIRST_S, EMAIL_EVERY_S = 120, 300
RECONCILE_EVERY_S = 1800
MAX_AGE = timedelta(hours=48)

# Stopped reasons worth a watch row beyond the review parks. The tab-blocked ones act the moment the block
# disappears from that tab (the human solved the captcha / logged in); the rerun ones just burn one watch_cycle
# after a wait, hoping the site behaves next time — SubmitWatcher._requeue keeps the count on the queue row.
_GATED = ("challenge", "auth_wall")
_GATE_PREFIX = "gate:"                          # gate:recaptcha_v2_checkbox, gate:cloudflare_interstitial, ...
_TRY_AGAIN = ("no_entry", "stuck", "site_refused")
_WATCH_MAX_CYCLES = 3
RETRY_AFTER_S = 15 * 60


def watchable(how: str) -> bool:
    """Is this stopped_reason worth a watch row at all?"""
    return how in _GATED + _TRY_AGAIN or how.startswith(_GATE_PREFIX)


def _gated(how: str) -> bool:
    """The block lives in the tab itself, so it can be cleared by hand while the tab sits there."""
    return how in _GATED or how.startswith(_GATE_PREFIX)


def cutoff_ts() -> str:
    """run_log.ts is a naive UTC isoformat — compare in kind."""
    return (datetime.now(timezone.utc) - MAX_AGE).replace(tzinfo=None).isoformat()


class SubmitWatcher:
    def __init__(self, db_path: str, cdp_url: str = "http://localhost:9222", interval_s: int = POLL_S, on_requeue=None):
        self.db_path, self.cdp_url, self.interval_s = db_path, cdp_url, interval_s
        self.on_requeue = on_requeue                  # called with no args after a re-queue: kick the queue runner
        self._thread: threading.Thread | None = None
        self._last_email: dict = {}
        self._last_reconcile = 0.0

    # -- registration (called by the queue runner when a run parks with its form left open) --------------------------
    def register(self, conn, job_id: int, url: str, run_key: str | None, tab_id: str | None, how: str = "manual") -> None:
        autonomy.ensure(conn)
        if watchable(how) and not self._cycles_left(conn, job_id, how):
            return
        conn.execute("INSERT OR REPLACE INTO submission_watch (job_id, url, run_key, last_values, created_at, tab_id, how) "
                     "VALUES (?,?,?,?,?,?,?)", (job_id, url, run_key, "{}", datetime.now(timezone.utc).isoformat(), tab_id, how))
        conn.commit()

    @staticmethod
    def _cycles_left(conn, job_id: int, how: str) -> bool:
        """Each finished re-queue burns one watch_cycle on the queue row; after _WATCH_MAX_CYCLES the job stays failed."""
        row = conn.execute("SELECT watch_cycles FROM apply_queue WHERE job_id=?", (job_id,)).fetchone()
        cycles = (row[0] or 0) if row else 0
        if cycles >= _WATCH_MAX_CYCLES:
            print(f"[watch] job {job_id}: {how} re-tried {cycles} time(s) already — leaving it failed", flush=True)
            return False
        return True

    # -- one pass -------------------------------------------------------------------------------------------------
    def poll_once(self, conn, tabs, email_check=None) -> list[int]:
        """`tabs.find(tab_id, url)` -> a tab with .url / .read_values() / .confirmed(), or None. `email_check(company, title,
        after_epoch)` -> {subject, from, date} or None: the confirmation email as a second proof (also covers a tab that was
        closed). Returns the job ids finalized this pass."""
        autonomy.ensure(conn)
        done = []
        rows = conn.execute(
            "SELECT w.job_id, w.url, w.run_key, w.last_values, w.created_at, w.tab_id, w.how, j.company, j.title "
            "FROM submission_watch w LEFT JOIN jobs j ON j.id = w.job_id").fetchall()
        for job_id, url, run_key, last, created, tab_id, how, company, title in rows:
            tab = tabs.find(tab_id, url)
            proof = None
            if tab is not None:
                ok, why = tab.confirmed()
                values = {autonomy.key(k): v for k, v in (tab.read_values() or {}).items()}
                if ok:
                    proof = why
                elif values:                                  # the form is still there: remember what it holds
                    conn.execute("UPDATE submission_watch SET last_values=? WHERE job_id=?", (json.dumps(values), job_id))
                    conn.commit()
            created_dt = datetime.fromisoformat(created)
            if proof is None and watchable(how or ""):
                verdict = self._blocked_poll(conn, job_id, url, tab, how or "", created_dt)
                if verdict == "requeued":
                    continue
                if verdict is None:                           # still blocked (or too soon to retry): give it MAX_AGE
                    if datetime.now(timezone.utc) - created_dt > MAX_AGE:
                        conn.execute("DELETE FROM submission_watch WHERE job_id=?", (job_id,))
                        conn.commit()
                    continue
                proof = verdict
            if proof is None and email_check and company and self._email_due(job_id, created_dt):
                hit = email_check(company, title or "", int(created_dt.timestamp()) - 600)
                if hit:
                    proof = f"email {hit.get('subject')!r} from {hit.get('from')}"
            if proof is None:
                if tab is None and datetime.now(timezone.utc) - created_dt > MAX_AGE:
                    conn.execute("DELETE FROM submission_watch WHERE job_id=?", (job_id,))
                    conn.commit()
                continue
            self._finalize(conn, job_id, run_key or "", last, how or "manual", url,
                           (getattr(tab, "url", None) if tab else None) or url, proof)
            if tab is not None and hasattr(tab, "close"):    # the confirmation page has nothing left to do: free the tab
                tab.close()
            done.append(job_id)
        return done

    def _finalize(self, conn, job_id: int, run_key: str, last: str, how: str, url: str, tab_url: str, proof: str) -> None:
        """The application went in: mark applied, file the submit and turn the form's final values into approvals."""
        out = autonomy.record_submission(conn, job_id, run_key, json.loads(last or "{}"), how or "manual", tab_url or url)
        set_job_status(conn, job_id, "applied")
        try:                                          # an account made inside that application exists now
            from career_agent.browser.credential_provider import confirm_pending_credentials
            confirm_pending_credentials(tab_url or url)
        except Exception:
            pass
        conn.execute("DELETE FROM submission_watch WHERE job_id=?", (job_id,))
        conn.commit()
        print(f"[watch] job {job_id} submitted ({proof}); approvals {out}", flush=True)

    def _blocked_poll(self, conn, job_id: int, url: str, tab, how: str, created_dt) -> str | None:
        """One pass on a watch row from a run that stopped inside a block.
        None -> keep waiting. "requeued" -> the job is back in the queue (row removed). Anything else is submit
        proof: the block is gone and the page confirms the application, so the caller finalizes with it."""
        if tab is not None and _gated(how):
            from career_agent.boards.profiles import board_for
            state = tab.blocked(board_for(url) or {})
            if state:                                        # still the challenge / login wall (or unreadable)
                return None
            ok, why = tab.confirmed()
            if ok:
                return f"{how} cleared; {why}"
            self._requeue(conn, job_id, f"{how} cleared by hand", url)
            return "requeued"
        if (datetime.now(timezone.utc) - created_dt).total_seconds() < RETRY_AFTER_S:
            return None                                      # rerun reasons get one quiet attempt later
        self._requeue(conn, job_id, how, url)
        return "requeued"

    def _requeue(self, conn, job_id: int, why: str, url: str) -> None:
        """Get the job run again: the app hands the watcher a relauncher (same single-flight the UI uses);
        without one, fall back to back of the apply queue. Unless it is already settled."""
        from job_dashboard.apply import queue as q
        row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row and row[0] in ("applied", "interviewing", "offer", "rejected", "closed"):
            print(f"[watch] job {job_id}: already {row[0]} — dropping the {why} watch", flush=True)
        else:
            taken = None
            if self.on_requeue:
                try:
                    taken = self.on_requeue(job_id, url)
                except Exception as e:
                    print(f"[watch] relaunch failed ({type(e).__name__}: {e}); falling back to the queue", flush=True)
            if not taken:
                q.enqueue(conn, job_id)
                print(f"[watch] job {job_id}: {why} -> re-queued", flush=True)
            else:
                print(f"[watch] job {job_id}: {why} -> re-running", flush=True)
            conn.execute("UPDATE apply_queue SET watch_cycles = watch_cycles + 1 WHERE job_id=?", (job_id,))
            conn.commit()
        conn.execute("DELETE FROM submission_watch WHERE job_id=?", (job_id,))
        conn.commit()

    def _email_due(self, job_id: int, created: datetime) -> bool:
        """Check the inbox no sooner than 2 minutes after the form was left open, then at most every 5 minutes."""
        now = time.time()
        if now - created.timestamp() < EMAIL_FIRST_S or now - self._last_email.get(job_id, 0) < EMAIL_EVERY_S:
            return False
        self._last_email[job_id] = now
        return True

    # -- discovery: CLI runs, UI runs and queue runs all land in run_log ---------------------------------------------
    def register_fresh_blocks(self, conn) -> None:
        """Fill the watch from last 48h of run_log rows: the latest run per job whose stopped_reason is a
        block the human can clear on its tab (or a bare re-run). This is how runs started outside the
        apply queue — the UI button, the CLI — get watched without their launcher knowing anything."""
        try:
            rows = conn.execute("SELECT id, ts, url, job_id, stopped_reason, result_json FROM run_log "
                                "WHERE job_id IS NOT NULL AND ts >= ? ORDER BY id DESC LIMIT 200",
                                (cutoff_ts(),)).fetchall()
        except sqlite3.OperationalError:            # run_log exists only once an agent has run against this DB
            return
        latest: dict[int, tuple] = {}
        for rid, ts, url, job_id, reason, rj in rows:
            if job_id not in latest:
                latest[job_id] = (rid, url, reason, rj)
        for job_id, (rid, url, reason, rj) in latest.items():
            if not watchable(reason or ""):
                continue
            if conn.execute("SELECT 1 FROM submission_watch WHERE job_id=?", (job_id,)).fetchone():
                continue                            # someone (queue runner) already registered it
            queued = conn.execute("SELECT state FROM apply_queue WHERE job_id=?", (job_id,)).fetchone()
            if queued and queued[0] in ("queued", "running"):
                continue                            # it is already about to be re-run — nothing to watch yet
            settled = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if settled and settled[0] in ("applied", "interviewing", "offer"):
                continue
            run_key = tab_id = None
            try:
                rj = json.loads(rj or "{}") or {}
                run_key, tab_id = rj.get("run_key"), rj.get("final_tab_id")
            except (TypeError, ValueError):
                pass
            self.register(conn, job_id, url, run_key or f"run{rid}", tab_id, reason)

    # -- background loop ------------------------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="submit-watch", daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while True:
            time.sleep(self.interval_s)
            try:
                conn = init_db(self.db_path)
                try:
                    autonomy.ensure(conn)
                    self.register_fresh_blocks(conn)
                    self._reconcile_if_due(conn)
                    if conn.execute("SELECT 1 FROM submission_watch LIMIT 1").fetchone():
                        with CdpTabs(self.cdp_url) as tabs:
                            self.poll_once(conn, tabs, self._email_check(conn))
                finally:
                    conn.close()
            except Exception as e:                            # Chrome closed, DB busy...: try again next pass
                print(f"[watch] pass skipped ({type(e).__name__}: {e})", flush=True)


    def _reconcile_if_due(self, conn) -> None:
        """Every 30 minutes: retire open questions on jobs whose lifecycle settled
        while they waited, and — with the Gmail switch on — mark tracked jobs
        applied from their confirmation emails."""
        from job_dashboard import qa_store
        if time.time() - self._last_reconcile < RECONCILE_EVERY_S:
            return
        self._last_reconcile = time.time()
        retired = qa_store.resolve_settled_questions(conn)
        if retired:
            print(f"[watch] retired {retired} open question(s) on settled jobs", flush=True)
        if qa_store.get_setting(conn, "gmail_confirmation_check") != "1":
            return
        from career_agent.integrations.gmail_confirm import list_confirmations
        from job_dashboard.apply.reconcile import reconcile
        rep = reconcile(conn, list_confirmations(int(time.time()) - 14 * 86400))
        if rep["matched"]:
            print(f"[watch] marked applied from email: {[m['job_id'] for m in rep['matched']]}", flush=True)

    @staticmethod
    def _email_check(conn):
        """The Gmail confirmation lookup, only while the user has the setting on (off by default, revocable)."""
        from job_dashboard import qa_store
        if qa_store.get_setting(conn, "gmail_confirmation_check") != "1":
            return None
        from career_agent.integrations.gmail_confirm import find_confirmation
        return find_confirmation


class _Tab:
    def __init__(self, page):
        self.page = page
        self.url = page.url

    def confirmed(self):
        from career_agent.browser.confirmation import page_confirmed
        return page_confirmed(self.page)

    def blocked(self, board):
        """The board's own blocker check (challenge / login wall) on this tab, or None when the page acts normally."""
        from career_agent.boards.run import _blocked
        try:
            return _blocked(self.page, board)
        except Exception:
            return "unreadable"                           # cannot read the page: never assume the block is gone

    def read_values(self):
        from career_agent.browser.form_values import read_form_values
        return read_form_values(self.page)

    def close(self):
        try:
            self.page.close()
        except Exception:
            pass


class CdpTabs:
    """The Chrome the agent drives, reached over CDP. Finds a tab by Chrome's own id (survives navigation), else by URL."""

    def __init__(self, cdp_url: str):
        self.cdp_url = cdp_url

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        try:
            # never wake tabs from a background watcher: that flips through the user's tabs every pass; a pass that
            # cannot attach just waits for the next one
            self._browser = self._pw.chromium.connect_over_cdp(self.cdp_url, timeout=30000)
        except BaseException:
            # __exit__ never runs when __enter__ raises: a playwright left started keeps its event loop in this
            # thread, and every later pass then fails "Sync API inside the asyncio loop" (live 2026-10-17: 453
            # skipped passes, no hand submit tracked) — stop it here
            self._pw.stop()
            raise
        return self

    def __exit__(self, *a):
        try:
            self._pw.stop()
        except Exception:
            pass

    def find(self, tab_id, url):
        pages = self._browser.contexts[0].pages if self._browser.contexts else []
        want = None
        if tab_id:
            try:
                for t in json.load(urllib.request.urlopen(self.cdp_url + "/json/list", timeout=3)):
                    if t.get("id") == tab_id:
                        want = t.get("url")
            except Exception:
                pass
        for target in (want, url):
            if not target:
                continue
            for pg in pages:
                if pg.url.split("#")[0] == target.split("#")[0]:
                    return _Tab(pg)
        return None
