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
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from job_dashboard import qa_store
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

    def stop(self) -> None:
        """Terminate the current run (SIGTERM, then SIGKILL after 5s)."""
        with self._lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def wait(self) -> int:
        """Block until the current run exits; its exit code (0 if nothing ran)."""
        with self._lock:
            proc = self._proc
        return 0 if proc is None else proc.wait()


def _cdp_reachable(cdp_url: str, timeout: float = 1.5) -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=timeout):
            return True
    except Exception:
        return False


def _any_chrome_running() -> bool:
    """True if any Google Chrome process is running — including ones without
    the debug port. Used to decide whether auto-launching the career-agent
    Chrome is safe (nothing open to disturb)."""
    try:
        return subprocess.run(["pgrep", "-x", "Google Chrome"],
                              capture_output=True).returncode == 0
    except Exception:
        return True  # can't tell -> assume yes, the non-destructive default


_CDP_CHROME_PROFILE_DIR = Path.home() / ".career_agent" / "chrome-p3"
_CDP_CHROME_PROFILE_NAME = "Profile 3"
_CDP_CHROME_APP = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _launch_cdp_chrome(port: int) -> None:
    subprocess.Popen(
        [_CDP_CHROME_APP, f"--remote-debugging-port={port}",
         f"--user-data-dir={_CDP_CHROME_PROFILE_DIR}",
         f"--profile-directory={_CDP_CHROME_PROFILE_NAME}",
         "--no-first-run", "--no-default-browser-check"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _ensure_cdp_chrome(cdp_url: str) -> Optional[str]:
    """Make the career-agent Chrome reachable before launching the agent
    against it. Returns None once it's ready (or already was), or an error
    message if it couldn't be made ready — never raises.

    Only auto-launches when NO Chrome process is running at all. macOS
    treats Chrome as single-instance: launching a second one with
    --remote-debugging-port while another Chrome window is already open just
    focuses that window and silently ignores the flag, so the documented
    manual recovery (career_agent/CLAUDE.md) does `pkill -x "Google Chrome"`
    first. Killing the user's existing Chrome closes their tabs/windows —
    a real, disruptive action — so this never does that automatically; it
    surfaces a clear error with the manual command instead.
    """
    if _cdp_reachable(cdp_url):
        return None
    if _any_chrome_running():
        return (f"career-agent Chrome isn't reachable at {cdp_url}, and Chrome is "
                "already running without the debug port. Auto-restarting it would "
                "close your existing Chrome windows, so that wasn't done — close "
                "Chrome yourself and try again, or run the launch command from "
                "career_agent/CLAUDE.md.")
    from urllib.parse import urlparse
    port = urlparse(cdp_url).port or 9222
    _launch_cdp_chrome(port)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if _cdp_reachable(cdp_url):
            return None
        time.sleep(0.5)
    return f"Launched career-agent Chrome but it didn't come up at {cdp_url} within 10s."


def _log_path(job_id: int) -> Path:
    return REPO_ROOT / "data" / "agent_runs" / f"{job_id}.log"


def _tail_log(job_id: int, lines: int = 80, max_bytes: int = 65536) -> Optional[list[str]]:
    """Last `lines` lines of the agent subprocess's stdout/stderr, or None if
    no log exists. Reads only the final `max_bytes`, so a long run stays cheap
    to poll every second."""
    path = _log_path(job_id)
    if not path.exists():
        return None
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        data = f.read()
    text = data.decode("utf-8", errors="replace")
    out = text.splitlines()
    if size > max_bytes and out:
        out = out[1:]  # first line is likely cut mid-line
    return [_clip(l) for l in out[-lines:]]


def _clip(line: str, limit: int = 400) -> str:
    """The agent sometimes prints its whole state dict on one line (JD HTML,
    every form control) — kilobytes that make a live log unreadable."""
    return line if len(line) <= limit else f"{line[:limit]}… [+{len(line) - limit} chars]"


def _live_screenshot_path(job_id: int) -> Path:
    return REPO_ROOT / "data" / "agent_runs" / str(job_id) / "live.png"


def _run_page(ctx, job_id):
    """The tab the run records in tab.json (apply.py); the last tab only when it recorded none."""
    import json
    pages = ctx.pages if ctx else []
    try:
        want = json.loads((_live_screenshot_path(job_id).parent / "tab.json").read_text()).get("tab_id")
    except (OSError, ValueError):
        want = None
    for pg in pages if want else ():
        try:
            if ctx.new_cdp_session(pg).send("Target.getTargetInfo")["targetInfo"]["targetId"] == want:
                return pg
        except Exception:
            continue
    return pages[-1] if pages else None


def _read_live_page(cdp_url: str, job_id: int) -> dict:
    """Read-only peek at the page career_agent is currently driving: url,
    title, and (if the screenshot save succeeds) a saved screenshot.

    Opens its OWN connect_over_cdp session onto the same debug port
    career_agent uses — Chrome supports multiple attached CDP clients on one
    target. This client only ever calls .url / .title() / .screenshot() and
    then disconnects (browser.close() on a CDP-attached session detaches
    Playwright's session; it does not close the browser process or any tab —
    verified empirically before relying on it here). It must never call
    .click() / .fill() / .goto() — career_agent is the one actually driving
    that page, and a second writer would race it.

    Returns a filesystem path (not a URL — the router turns that into a
    servable URL if present) so this function stays free of API concerns.
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
                page = _run_page(ctx, job_id)
                if page is None:
                    return {"url": None, "title": None, "screenshot_path": None}
                url, title = page.url, page.title()
                ss_path = _live_screenshot_path(job_id)
                ss_path.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(ss_path))
                return {"url": url, "title": title, "screenshot_path": ss_path}
            finally:
                browser.close()  # detaches this session only — see docstring
    except Exception:
        return {"url": None, "title": None, "screenshot_path": None}


def _with_questions(job_id, steps, by_page) -> dict:
    """The run's pages, each with the questions asked on it; rows with no page
    (older runs) come back under `unpaged`."""
    for s in steps:
        s["questions"] = by_page.get(s["step"], [])
    return {"job_id": job_id, "steps": steps, "unpaged": by_page.get(None, [])}


def _with_eligibility(run_dir, body):
    """Add the run's auto-submit verdict (autonomy.autosubmit_policy), if the run recorded one."""
    import json
    try:
        body = dict(body)
        body["eligibility"] = json.loads((run_dir / "eligibility.json").read_text())
    except (OSError, ValueError, TypeError):
        pass
    return body


def build_agent_router(db_path, state: Optional[AgentRunState] = None) -> APIRouter:
    router = APIRouter()
    state = state or AgentRunState()      # shared with the apply queue's runner

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
        job_url = (detail["apply_url"] if detail.get("apply_kind") == "external" and detail.get("apply_url")
                   else detail.get("job_url"))
        if not job_url:
            raise HTTPException(status_code=422, detail="job has no job_url")

        from career_agent.config.settings import load_settings
        cdp_url = load_settings().cdp_url
        if cdp_url:
            problem = _ensure_cdp_chrome(cdp_url)
            if problem:
                raise HTTPException(status_code=503, detail=problem)

        from job_dashboard.apply import local_model
        local_model.ensure_running()                 # the drafting model; left running for this single run
        cmd = [sys.executable, "-m", "career_agent.apply",
               "--job-id", str(job_id), "--url", job_url, "--claude-assist"]   # same as the queue: capped at 5 calls
        env = {**os.environ, "PYTHONPATH": "src", "PYTHONUNBUFFERED": "1"}
        log_path = _log_path(job_id)
        started = state.start(job_id, cmd, str(REPO_ROOT), env, log_path)
        if not started:
            raise HTTPException(status_code=409, detail="agent already running")
        return {"started": True, "job_id": job_id}

    @router.post("/api/open-in-agent-chrome")
    def open_in_agent_chrome(body: dict):
        """Open a URL as a new tab in the career-agent Chrome (CDP), so job/ATS
        links land in the logged-in agent profile instead of the dashboard's browser."""
        from urllib.parse import quote, urlparse
        import urllib.request
        url = str(body.get("url") or "")
        if urlparse(url).scheme not in ("http", "https"):
            raise HTTPException(status_code=422, detail="url must be http(s)")
        from career_agent.config.settings import load_settings
        cdp_url = load_settings().cdp_url or "http://localhost:9222"
        problem = _ensure_cdp_chrome(cdp_url)
        if problem:
            raise HTTPException(status_code=503, detail=problem)
        req = urllib.request.Request(f"{cdp_url}/json/new?{quote(url, safe='')}", method="PUT")
        try:
            urllib.request.urlopen(req, timeout=5).close()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"CDP open failed: {e}")
        return {"opened": True}

    @router.get("/api/apply-agent/status")
    def agent_status():
        snapshot = state.poll()
        if not snapshot["running"]:
            return snapshot
        from career_agent.config.settings import load_settings
        cdp_url = load_settings().cdp_url
        live = ({"url": None, "title": None, "screenshot_path": None} if not cdp_url
                else _read_live_page(cdp_url, snapshot["job_id"]))
        screenshot = (f"/api/jobs/{snapshot['job_id']}/agent-runs/live-screenshot"
                     if live["screenshot_path"] else None)
        return {**snapshot, "url": live["url"], "title": live["title"], "screenshot": screenshot}

    @router.get("/api/jobs/{job_id}/agent-runs/log")
    def agent_log(job_id: int, lines: int = 80):
        lines = max(1, min(lines, 500))
        tail = _tail_log(job_id, lines)
        if tail is None:
            raise HTTPException(status_code=404, detail="no log for this job")
        return {"job_id": job_id, "lines": tail}

    @router.get("/api/jobs/{job_id}/agent-runs/live-screenshot")
    def agent_live_screenshot(job_id: int):
        path = _live_screenshot_path(job_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="no live screenshot yet")
        return FileResponse(path, media_type="image/png")

    @router.get("/api/jobs/{job_id}/agent-runs/screenshot/{step}")
    def agent_step_screenshot(job_id: int, step: int, part: int = 1):
        """`part` > 1 = the next scrolled segment of a long page (perceive<N>_<part>.png)."""
        name = f"perceive{step}.png" if part <= 1 else f"perceive{step}_{part}.png"
        path = REPO_ROOT / "data" / "agent_runs" / str(job_id) / name
        if not path.exists():
            raise HTTPException(status_code=404, detail="no screenshot for this step")
        return FileResponse(path, media_type="image/png")

    @router.get("/api/jobs/{job_id}/agent-runs/latest")
    def agent_run_history(job_id: int):
        conn = db()
        try:
            detail = job_detail(conn, job_id)
            by_page = qa_store.questions_by_page(conn, job_id)
        finally:
            conn.close()
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")
        job_url = detail.get("job_url") or ""
        run_dir = REPO_ROOT / "data" / "agent_runs" / str(job_id)

        from career_agent.boards.profiles import board_for
        board_log = run_dir / "board_run.json"
        if board_for(job_url) and board_log.exists():      # board runs log themselves
            import json
            try:
                steps = json.loads(board_log.read_text())
            except ValueError:
                steps = []
            if not steps:
                raise HTTPException(status_code=404, detail="no agent run found for this job")
            for s in steps:
                s["screenshot"] = (f"/api/jobs/{job_id}/agent-runs/screenshot/{s['step']}"
                                   if s.get("screenshot") else None)
            return _with_eligibility(run_dir, _with_questions(job_id, steps, by_page))

        import hashlib
        from career_agent.orchestrator.run_history import summarize_run

        thread_id = hashlib.sha1(job_url.encode()).hexdigest()[:16]
        checkpoint_db = str(REPO_ROOT / "data" / "jobs_graph.db")
        steps = summarize_run(thread_id, checkpoint_db, run_dir=str(run_dir))
        if not steps:
            raise HTTPException(status_code=404, detail="no agent run found for this job")
        for s in steps:
            s["screenshot"] = (f"/api/jobs/{job_id}/agent-runs/screenshot/{s['step']}"
                               if s["screenshot"] else None)
        return _with_eligibility(run_dir, _with_questions(job_id, steps, by_page))

    return router
