"""One-shot CDP tab probe, run as a subprocess by the SubmitWatcher.

The dashboard server runs inside asyncio, where Playwright's Sync API refuses
to start ("It looks like you are using Playwright Sync API inside the asyncio
loop") — that made every 30-second watcher pass skip, forever. A fresh process
has no event loop, so the exact same checks work there.

Reads the single tab that matches --tab-id (Chrome's own id, else --url), runs
the three watcher questions — is the block still on, did the page confirm the
submit, what does the form hold — and prints one JSON line.
"""
from __future__ import annotations

import argparse
import json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdp-url", default="http://localhost:9222")
    ap.add_argument("--tab-id", default=None)
    ap.add_argument("--url", default=None)
    ap.add_argument("--board", default="{}")    # {'challenge': [...], 'logged_out': [...]} as JSON
    a = ap.parse_args()

    out = {"found": False, "url": None, "blocked": None, "confirmed": [False, "tab not found"], "values": {}}
    from job_dashboard.apply.submit_watch import CdpTabs
    with CdpTabs(a.cdp_url) as tabs:
        tab = tabs.find(a.tab_id, a.url)
        if tab is not None:
            out["found"] = True
            out["url"] = tab.url
            try:
                out["confirmed"] = list(tab.confirmed())
            except Exception as e:
                out["confirmed"] = [False, f"confirmed check failed: {type(e).__name__}"]
            try:
                out["blocked"] = tab.blocked(json.loads(a.board or "{}"))
            except Exception:
                out["blocked"] = "unreadable"
            try:
                out["values"] = tab.read_values() or {}
            except Exception:
                out["values"] = {}
    print(json.dumps(out))


if __name__ == "__main__":
    main()
