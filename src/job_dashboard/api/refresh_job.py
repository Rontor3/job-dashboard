import threading

from job_dashboard.db import init_db
from job_dashboard.pipeline import run_pipeline
from job_dashboard.source_registry import company_sources, job_sources


class RefreshState:
    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self.stage = "idle"
        self.detail = None
        self.last_result = None
        self.error = None

    def snapshot(self):
        with self._lock:
            return {
                "running": self._running, "stage": self.stage,
                "detail": self.detail, "last_result": self.last_result,
                "error": self.error,
            }

    def start(self, runner):
        """runner(on_stage) -> result dict. Returns False if already running."""
        with self._lock:
            if self._running:
                return False
            self._running = True
            self.stage = "starting"
            self.error = None

        def on_stage(stage):
            with self._lock:
                self.stage = stage

        def work():
            try:
                result = runner(on_stage)
                with self._lock:
                    self.last_result = result
                    self.stage = "done"
                    self.detail = _summarize(result)
            except Exception as exc:
                with self._lock:
                    self.stage = "error"
                    self.error = str(exc)
            finally:
                with self._lock:
                    self._running = False

        threading.Thread(target=work, daemon=True).start()
        return True


def _summarize(result):
    ingest = result.get("ingest", {})
    parts = [f"{ingest.get('new_jobs', 0)} new jobs",
             f"{result.get('embed_scored', 0)} scored"]
    if result.get("embed_skipped"):
        parts.append(f"scoring skipped: {result['embed_skipped']}")
    return ", ".join(parts)


def default_pipeline_runner(db_path, on_stage):
    conn = init_db(db_path)  # own connection: sqlite is per-thread
    try:
        return run_pipeline(conn, job_sources(), company_sources(), on_stage=on_stage)
    finally:
        conn.close()
