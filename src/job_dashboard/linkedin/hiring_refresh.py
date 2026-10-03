"""Run the hiring-post refresh on a background thread, one at a time, and expose
live progress. The caller supplies ``run(on_event)``; nothing here knows about
LinkedIn. State is in memory: a server restart forgets a finished run, which is
fine because the posts themselves are stored as they are scored."""
from __future__ import annotations

import threading
from datetime import datetime, timezone


class RefreshBusy(RuntimeError):
    pass


class HiringRefresh:
    def __init__(self):
        self._lock = threading.Lock()
        self._state = {"state": "idle"}
        self._thread = None

    def status(self) -> dict:
        return dict(self._state)

    def running(self) -> bool:
        return self._state.get("state") == "running"

    def _event(self, e: dict):
        self._state.update({k: v for k, v in e.items() if k != "stage"} | {"stage": e.get("stage")})

    def _work(self, run):
        try:
            run(self._event)
            self._state.update(state="done", stage="done")
        except Exception as e:  # noqa: BLE001 — surfaced in status, never raised into the thread
            self._state.update(state="error", error=str(e), error_type=type(e).__name__)
        finally:
            self._state["finished_at"] = datetime.now(timezone.utc).isoformat()

    def start(self, run, *, wait: bool = False):
        """Begin ``run(on_event)``. Raises RefreshBusy if one is already going.
        ``wait`` blocks until it finishes (used by the synchronous API path)."""
        with self._lock:
            if self.running():
                raise RefreshBusy("a refresh is already running")
            self._state = {"state": "running", "stage": "starting",
                           "started_at": datetime.now(timezone.utc).isoformat()}
            self._thread = threading.Thread(target=self._work, args=(run,), daemon=True)
            self._thread.start()
        if wait:
            self._thread.join()
        return self.status()
