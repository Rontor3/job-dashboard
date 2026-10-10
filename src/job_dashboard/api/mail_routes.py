"""Mail scan API + the once-a-day runner (see job_dashboard/mail_scan.py)."""
from __future__ import annotations

import threading
import time

from fastapi import APIRouter, HTTPException

from job_dashboard import mail_scan, qa_store
from job_dashboard.db import init_db


class MailScanner:
    """Runs a scan on a background thread; one at a time across processes (the api's "Scan now" and the worker's
    daily scan each have a scanner), through a lock file. The last result is kept in jobs.db for both to read."""

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

    @staticmethod
    def _lock_fd(blocking: bool = False) -> int | None:
        """An fd holding the scan lock, or None when another scan holds it."""
        import fcntl
        import os
        from job_dashboard import paths
        paths.STATE.mkdir(parents=True, exist_ok=True)
        fd = os.open(paths.STATE / "mail_scan.lock", os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            return fd
        except BlockingIOError:
            os.close(fd)
            return None

    def _run(self) -> None:
        import json
        import os
        fd = self._lock_fd()
        if fd is None:
            return                            # the other process is scanning
        conn = init_db(self.db_path)
        try:
            try:
                result = mail_scan.run_scan(conn, self.mailbox_factory(), self._llm())
            except Exception as e:            # run_scan never raises; this guards the factory
                result = {"scanned": 0, "matched": 0, "changes": [], "error": type(e).__name__}
            self.last_result = result
            qa_store.set_setting(conn, "mail_last_result", json.dumps(result))
        finally:
            conn.close()
            os.close(fd)

    def result(self) -> dict | None:
        """The last scan's result, whichever process ran it."""
        import json
        conn = init_db(self.db_path)
        try:
            raw = qa_store.get_setting(conn, "mail_last_result")
        finally:
            conn.close()
        return json.loads(raw) if raw else self.last_result

    def start(self) -> bool:
        with self._lock:
            if self.running:
                return False
            self._thread = threading.Thread(target=self._run, name="mail-scan", daemon=True)
            self._thread.start()
            return True

    @property
    def running(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return True
        fd = self._lock_fd()
        if fd is None:
            return True                       # a scan in the other process
        import os
        os.close(fd)
        return False

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
        result = scanner.result()
        return {"running": scanner.running, "last_scan": last, "last_result": result,
                "connected": not (result and result.get("error") == "gmail_not_connected")}

    return router
