"""Mail scan API + the once-a-day runner (see job_dashboard/mail_scan.py)."""
from __future__ import annotations

import threading
import time

from fastapi import APIRouter, HTTPException

from job_dashboard import mail_scan, qa_store
from job_dashboard.db import init_db


class MailScanner:
    """Runs a scan on a background thread; one at a time."""

    def __init__(self, db_path, mailbox_factory=None, llm=None):
        self.db_path = str(db_path)
        self.mailbox_factory = mailbox_factory or mail_scan.default_mailbox
        self.llm = llm
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.last_result: dict | None = None

    def _llm(self):
        if self.llm is not None:
            return self.llm
        try:
            from job_dashboard.letter.draft import make_default_llm
            return make_default_llm()
        except Exception:
            return None                      # keyword rules still classify

    def _run(self) -> None:
        conn = init_db(self.db_path)
        try:
            self.last_result = mail_scan.run_scan(conn, self.mailbox_factory(), self._llm())
        except Exception as e:                # run_scan never raises; this guards the factory
            self.last_result = {"scanned": 0, "matched": 0, "changes": [], "error": type(e).__name__}
        finally:
            conn.close()

    def start(self) -> bool:
        with self._lock:
            if self.running:
                return False
            self._thread = threading.Thread(target=self._run, name="mail-scan", daemon=True)
            self._thread.start()
            return True

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def run_if_due(self) -> bool:
        conn = init_db(self.db_path)
        try:
            due = mail_scan.is_due(conn)
        finally:
            conn.close()
        return self.start() if due else False

    def loop(self, every_s: int = 1800) -> None:
        """Blocking: check twice an hour, scan when a day has passed. For a daemon thread."""
        while True:
            try:
                self.run_if_due()
            except Exception as e:
                print(f"[mail-scan] check failed ({type(e).__name__})", flush=True)
            time.sleep(every_s)


def build_mail_router(db_path, scanner: MailScanner) -> APIRouter:
    router = APIRouter()

    @router.get("/api/jobs/{job_id}/mail")
    def job_mail(job_id: int):
        conn = init_db(db_path)
        try:
            return {"mail": mail_scan.mail_for_job(conn, job_id)}
        finally:
            conn.close()

    @router.post("/api/mail-scan")
    def scan_now():
        if not scanner.start():
            raise HTTPException(status_code=409, detail="a scan is already running")
        return {"started": True}

    @router.get("/api/mail-scan/status")
    def scan_status():
        conn = init_db(db_path)
        try:
            last = int(qa_store.get_setting(conn, "mail_last_scan"))
        finally:
            conn.close()
        result = scanner.last_result
        return {"running": scanner.running, "last_scan": last, "last_result": result,
                "connected": not (result and result.get("error") == "gmail_not_connected")}

    return router
