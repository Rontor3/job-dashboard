"""Launches career_agent against a job and reports its live/past status.

Kept as its own APIRouter (not inline in app.py) to respect the 500-line cap,
same as apply_routes.py / letter_routes.py / resume_routes.py.

career_agent runs as a **separate subprocess** (`python3 -m career_agent.apply`)
against the shared career-agent Chrome, never in-process — the two are
deliberately decoupled (see CLAUDE.md's front-half/back-half split). Live
status is read two ways: the subprocess's own exit state (running/done/error),
and a second, READ-ONLY `connect_over_cdp` client onto the same Chrome the
agent is driving, for the current page's url/title/screenshot. That second
client must never click/fill/navigate — see `_read_live_page`'s docstring.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

from job_dashboard.db import init_db, job_detail

REPO_ROOT = Path(__file__).resolve().parents[3]


class AgentRunState:
    """Single-flight lock: one career_agent run at a time, since there's one
    shared career-agent Chrome profile. Mirrors RefreshState's shape."""

    def __init__(self):
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._job_id: Optional[int] = None
        self._log_file = None

    def start(self, job_id: int, cmd: list[str], cwd: str, env: dict, log_path: Path) -> bool:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return False
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = open(log_path, "wb")
            self._proc = subprocess.Popen(
                cmd, cwd=cwd, env=env, stdout=self._log_file, stderr=subprocess.STDOUT,
            )
            self._job_id = job_id
            return True

    def poll(self) -> dict:
        """{"running": True, "job_id"} while active; {"running": False,
        "job_id", "status": "done"|"error", "exit_code"} once, right after it
        exits; {"running": False, "job_id": None} if nothing has ever run."""
        with self._lock:
            if self._proc is None:
                return {"running": False, "job_id": None}
            code = self._proc.poll()
            if code is None:
                return {"running": True, "job_id": self._job_id}
            job_id = self._job_id
            return {"running": False, "job_id": job_id,
                    "status": "done" if code == 0 else "error", "exit_code": code}


def _read_live_page(cdp_url: str, job_id: int) -> dict:
    """Read-only peek at the page career_agent is currently driving: url,
    title, and a screenshot saved to data/agent_runs/{job_id}/live.png.

    Opens its OWN connect_over_cdp session onto the same debug port
    career_agent uses — Chrome supports multiple attached CDP clients on one
    target. This client only ever calls .url / .title() / .screenshot() and
    then disconnects (browser.close() on a CDP-attached session detaches
    Playwright's session; it does not close the browser process or any tab —
    verified empirically before relying on it here). It must never call
    .click() / .fill() / .goto() — career_agent is the one actually driving
    that page, and a second writer would race it.

    Degrades to all-None on any failure (Chrome not up, no page, timeout) —
    the subprocess's own running/done/error state stays authoritative for
    "is it running"; this is best-effort extra detail only.
    """
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(cdp_url, timeout=5000)
            try:
                ctx = browser.contexts[0] if browser.contexts else None
                page = ctx.pages[-1] if ctx and ctx.pages else None
                if page is None:
                    return {"url": None, "title": None, "screenshot": None}
                url, title = page.url, page.title()
                ss_dir = REPO_ROOT / "data" / "agent_runs" / str(job_id)
                ss_dir.mkdir(parents=True, exist_ok=True)
                ss_path = ss_dir / "live.png"
                page.screenshot(path=str(ss_path))
                return {"url": url, "title": title, "screenshot": str(ss_path)}
            finally:
                browser.close()  # detaches this session only — see docstring
    except Exception:
        return {"url": None, "title": None, "screenshot": None}


def build_agent_router(db_path) -> APIRouter:
    router = APIRouter()
    state = AgentRunState()

    def db():
        return init_db(db_path)

    @router.post("/api/jobs/{job_id}/apply-agent")
    def start_agent(job_id: int):
        conn = db()
        try:
            detail = job_detail(conn, job_id)
        finally:
            conn.close()
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")
        job_url = detail.get("job_url")
        if not job_url:
            raise HTTPException(status_code=422, detail="job has no job_url")

        cmd = [sys.executable, "-m", "career_agent.apply",
               "--job-id", str(job_id), "--url", job_url]
        env = {**os.environ, "PYTHONPATH": "src"}
        log_path = REPO_ROOT / "data" / "agent_runs" / f"{job_id}.log"
        started = state.start(job_id, cmd, str(REPO_ROOT), env, log_path)
        if not started:
            raise HTTPException(status_code=409, detail="agent already running")
        return {"started": True, "job_id": job_id}

    @router.get("/api/apply-agent/status")
    def agent_status():
        snapshot = state.poll()
        if not snapshot["running"]:
            return snapshot
        from career_agent.config.settings import load_settings
        cdp_url = load_settings().cdp_url
        live = ({"url": None, "title": None, "screenshot": None} if not cdp_url
                else _read_live_page(cdp_url, snapshot["job_id"]))
        return {**snapshot, **live}

    @router.get("/api/jobs/{job_id}/agent-runs/latest")
    def agent_run_history(job_id: int):
        conn = db()
        try:
            detail = job_detail(conn, job_id)
        finally:
            conn.close()
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")
        job_url = detail.get("job_url") or ""

        import hashlib
        from career_agent.orchestrator.run_history import summarize_run

        thread_id = hashlib.sha1(job_url.encode()).hexdigest()[:16]
        checkpoint_db = str(REPO_ROOT / "data" / "jobs_graph.db")
        run_dir = str(REPO_ROOT / "data" / "agent_runs" / str(job_id))
        steps = summarize_run(thread_id, checkpoint_db, run_dir=run_dir)
        if not steps:
            raise HTTPException(status_code=404, detail="no agent run found for this job")
        return {"job_id": job_id, "steps": steps}

    return router
