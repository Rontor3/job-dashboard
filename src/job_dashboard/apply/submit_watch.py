"""Notice when a parked application is submitted by hand.

A run that stops for review leaves its form open in Chrome. When the human submits it there, nothing used to tell the
dashboard. The watcher keeps one row per such job (the tab, the run) and, every poll, (1) remembers what the form
holds, (2) checks whether the tab now confirms the application. On confirmation it marks the job applied, files the
submit in the history and turns the form's final values into approvals (autonomy.record_submission): what was left
as the agent filled it is approved, what you changed is reset. It only reads; it never clicks or types."""
from __future__ import annotations

import json
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


class SubmitWatcher:
    def __init__(self, db_path: str, cdp_url: str = "http://localhost:9222", interval_s: int = POLL_S):
        self.db_path, self.cdp_url, self.interval_s = db_path, cdp_url, interval_s
        self._thread: threading.Thread | None = None
        self._last_email: dict = {}
        self._last_reconcile = 0.0

    # -- registration (called by the queue runner when a run parks with its form left open) --------------------------
    def register(self, conn, job_id: int, url: str, run_key: str | None, tab_id: str | None, how: str = "manual") -> None:
        autonomy.ensure(conn)
        conn.execute("INSERT OR REPLACE INTO submission_watch (job_id, url, run_key, last_values, created_at, tab_id, how) "
                     "VALUES (?,?,?,?,?,?,?)", (job_id, url, run_key, "{}", datetime.now(timezone.utc).isoformat(), tab_id, how))
        conn.commit()

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
            if proof is None and email_check and company and self._email_due(job_id, created_dt):
                hit = email_check(company, title or "", int(created_dt.timestamp()) - 600)
                if hit:
                    proof = f"email {hit.get('subject')!r} from {hit.get('from')}"
            if proof is None:
                if tab is None and datetime.now(timezone.utc) - created_dt > MAX_AGE:
                    conn.execute("DELETE FROM submission_watch WHERE job_id=?", (job_id,))
                    conn.commit()
                continue
            out = autonomy.record_submission(conn, job_id, run_key or "", json.loads(last or "{}"), how or "manual",
                                             (getattr(tab, "url", None) if tab else None) or url)
            set_job_status(conn, job_id, "applied")
            conn.execute("DELETE FROM submission_watch WHERE job_id=?", (job_id,))
            conn.commit()
            print(f"[watch] job {job_id} submitted ({proof}); approvals {out}", flush=True)
            done.append(job_id)
        return done

    def _email_due(self, job_id: int, created: datetime) -> bool:
        """Check the inbox no sooner than 2 minutes after the form was left open, then at most every 5 minutes."""
        now = time.time()
        if now - created.timestamp() < EMAIL_FIRST_S or now - self._last_email.get(job_id, 0) < EMAIL_EVERY_S:
            return False
        self._last_email[job_id] = now
        return True

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
                    self._reconcile_if_due(conn)
                    if conn.execute("SELECT 1 FROM submission_watch LIMIT 1").fetchone():
                        with CdpTabs(self.cdp_url) as tabs:
                            self.poll_once(conn, tabs, self._email_check(conn))
                finally:
                    conn.close()
            except Exception as e:                            # Chrome closed, DB busy...: try again next pass
                print(f"[watch] pass skipped ({type(e).__name__}: {e})", flush=True)


    def _reconcile_if_due(self, conn) -> None:
        """Every 30 minutes, with the Gmail switch on: mark tracked jobs applied from their confirmation emails."""
        from job_dashboard import qa_store
        if time.time() - self._last_reconcile < RECONCILE_EVERY_S or qa_store.get_setting(conn, "gmail_confirmation_check") != "1":
            return
        self._last_reconcile = time.time()
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

    def read_values(self):
        from career_agent.browser.form_values import read_form_values
        return read_form_values(self.page)


class CdpTabs:
    """The Chrome the agent drives, reached over CDP. Finds a tab by Chrome's own id (survives navigation), else by URL."""

    def __init__(self, cdp_url: str):
        self.cdp_url = cdp_url

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.connect_over_cdp(self.cdp_url)
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
