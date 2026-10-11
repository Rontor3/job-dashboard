"""The queue's hand-off to the in-app agent (apply_engine=agent): start a background agent session for the job, then
wait until the run reaches a verdict in `apply_run` (the agent's tools write it through the api).

    AGENT_URL  the agent service (default http://127.0.0.1:8000)
    API_URL    FastAPI (default http://127.0.0.1:8001)"""
from __future__ import annotations

import json
import os
import time
import urllib.request

from job_dashboard.apply.run_store import TERMINAL

RUN_TIMEOUT_S = 25 * 60
POLL_S = 3


def _http(method: str, url: str, body: dict | None = None, timeout: float = 30) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def run_with_agent(job_id: int, http=_http, sleep=time.sleep, clock=time.monotonic,
                   timeout_s: float = RUN_TIMEOUT_S) -> dict:
    """The run's final apply_run row ({state, reason, detail, ...}); state 'failed' if it never got one."""
    agent = os.getenv("AGENT_URL", "http://127.0.0.1:8000").rstrip("/")
    api = os.getenv("API_URL", "http://127.0.0.1:8001").rstrip("/")
    before = http("GET", f"{api}/api/apply-sessions/{job_id}").get("updated_at")
    started = http("POST", f"{agent}/agent/runs", {"job_id": job_id})
    end = clock() + timeout_s
    while clock() < end:
        row = http("GET", f"{api}/api/apply-sessions/{job_id}")
        if row.get("updated_at") != before and row.get("state") in TERMINAL:
            return {**row, "agent_session": started.get("session")}
        sleep(POLL_S)
    try:
        http("POST", f"{api}/api/apply-sessions/{job_id}/pause",
             {"reason": "error", "detail": "the agent did not finish this run in time", "questions": []})
    except Exception:
        pass
    return {"state": "failed", "reason": "agent_timeout", "agent_session": started.get("session")}


def queue_verdict(row: dict) -> tuple[str, str | None]:
    """apply_run verdict -> (apply_queue state, reason)."""
    state = row.get("state")
    if state == "submitted":
        return "done", None
    if state == "paused":
        return "parked", row.get("reason") or "needs_answers"
    return "failed", row.get("reason") or state or "error"
