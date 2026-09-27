"""Board profiles: `board` nodes in ats-graph.json say which job board a URL
belongs to and how its apply flow is driven (entry control, questionnaire
source, confirmation response, logged-out / challenge tells, daily cap).
Data only — drivers in drivers.py read these fields."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

GRAPH = Path(__file__).resolve().parents[3] / "docs/career-agent/ats-graph.json"

_DEFAULTS = {
    "advance": ["Next", "Continue", "Review"],
    "final": ["Submit application", "Submit your application", "Send application", "Submit"],
    "logged_out": [],
    "interstitial": [],
    "daily_cap": 20,
}
# Bot-challenge tells shared by every board (page URL / visible text); a board
# node's own `challenge` list extends these.
_CHALLENGE = ["verify you are human", "unusual activity", "are you a robot",
              "security check", "just a moment", "additional verification required",
              "cdn-cgi/challenge", "challenges.cloudflare.com"]


def load_boards(path=GRAPH) -> list[dict]:
    try:
        nodes = json.loads(Path(path).read_text())["nodes"]
    except Exception:
        return []
    return [{**_DEFAULTS, **n, "challenge": _CHALLENGE + n.get("challenge", [])}
            for n in nodes if n.get("type") == "board"]


def board_for(url, boards=None):
    """The board profile whose domain is the URL's host or a parent of it, else None."""
    host = (urlparse(url or "").hostname or "").lower()
    if not host:
        return None
    for b in load_boards() if boards is None else boards:
        if any(host == d or host.endswith("." + d) for d in b.get("domains", [])):
            return b
    return None


_STEP = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def json_path(obj, path):
    """'jobs[0].questionnaire' -> value, or None when any step is missing."""
    for key, idx in _STEP.findall(path or ""):
        try:
            obj = obj[int(idx)] if idx else obj[key]
        except (KeyError, IndexError, TypeError, ValueError):
            return None
    return obj
