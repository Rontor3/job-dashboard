"""Pure board signals: bot challenge, logged-out, and the board's own proof that
an application went in. No browser calls — callers pass the page URL, visible
text and the captured network responses (Playwright Response-like objects).

A `confirm` rule is either {"page_url": fragment} or matched against one
response: `capture` (URL fragment, required), optional `status`,
`request_match` (regex on the request body) and `path` + `match` (regex on the
JSON value at that path)."""
from __future__ import annotations

import json
import re

from .profiles import json_path


def _hit(needles, url, text):
    u, t = (url or "").lower(), (text or "").lower()
    return any(n.lower() in u or n.lower() in t for n in needles)


def is_challenge(board, url, text):
    return _hit(board.get("challenge", []), url, text)


def is_logged_out(board, url, text):
    return _hit(board.get("logged_out", []), url, text)


def _json(resp):
    try:
        return resp.json()
    except Exception:
        return None


def _request_body(resp):
    try:
        return resp.request.post_data or ""
    except Exception:
        return ""


def rule_matches(rule, resp):
    if not rule.get("capture") or rule["capture"] not in resp.url:
        return False
    if "status" in rule and getattr(resp, "status", None) != rule["status"]:
        return False
    if rule.get("request_match") and not re.search(rule["request_match"], _request_body(resp)):
        return False
    if rule.get("path"):
        val = json_path(_json(resp), rule["path"])
        text = val if isinstance(val, str) else json.dumps(val)
        if val is None or not re.search(rule.get("match", "."), text, re.I):
            return False
    return True


def confirmed(board, responses, page_url=""):
    """True only when the board's own response or landing URL proves the apply."""
    for rule in board.get("confirm", []):
        if rule.get("page_url"):
            if rule["page_url"] in (page_url or ""):
                return True
        elif any(rule_matches(rule, r) for r in responses):
            return True
    return False
