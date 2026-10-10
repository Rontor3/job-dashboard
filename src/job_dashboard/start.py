"""Start the dashboard and show it as a tab in the agent's Chrome, the one window where every agent run opens too.

    PYTHONPATH=src uv run python -m job_dashboard.start [--port 8000] [--no-browser]
"""
from __future__ import annotations

import argparse
import threading
import time
import urllib.request

from job_dashboard import agent_browser


def _answers(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=1).close()
        return True
    except Exception:
        return False


def show_dashboard(url: str, wait_s: float = 60, server_up=_answers, sleep=time.sleep) -> str | None:
    """Once the server answers, put ``url`` in the agent window: launch Chrome on it, or focus/open its tab.
    None on success, else a reason."""
    deadline = time.monotonic() + wait_s
    while not server_up(url):
        if time.monotonic() >= deadline:
            return f"dashboard didn't answer at {url} within {wait_s:.0f}s"
        sleep(0.5)
    if not agent_browser.reachable():
        return agent_browser.ensure_running(start_url=url, window=lambda u: None)
    return None if agent_browser.show_tab(url) else "couldn't open the dashboard tab in the agent browser"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true", help="serve only; don't open the agent browser")
    args = ap.parse_args(argv)
    url = f"http://localhost:{args.port}"

    if not args.no_browser:
        def show():
            problem = show_dashboard(url)
            print(f"[start] {problem} — open {url} yourself" if problem else f"[start] dashboard open in the agent browser: {url}",
                  flush=True)
        threading.Thread(target=show, name="show-dashboard", daemon=True).start()

    import uvicorn
    uvicorn.run("job_dashboard.api.serve:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
