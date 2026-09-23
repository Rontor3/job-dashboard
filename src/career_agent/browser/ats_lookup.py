"""Match a job URL to a known ATS vendor from ats-graph.json.

Cross-vendor pattern lookup:
  lookup(url)          → vendor node + fix_hints for known errors on that vendor
  find_fixes(symptom)  → errors/fixes matching a symptom across ALL vendors
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from urllib.parse import urlparse

_GRAPH = Path(__file__).resolve().parents[3] / "docs/career-agent/ats-graph.json"

# Vendors commonly seen but missing from the graph or lacking domain entries
_FALLBACK: dict[str, dict] = {
    "lever.co":        {"id": "vendor:lever",      "label": "Lever",      "notes": "Direct, no-login. Clean fillable class names."},
    "greenhouse.io":   {"id": "vendor:greenhouse",  "label": "Greenhouse", "notes": "Direct form, no login. Standard HTML inputs."},
    "ashbyhq.com":     {"id": "vendor:ashby",       "label": "Ashby",      "notes": "React SPA. reCAPTCHA on some forms."},
    "icims.com":       {"id": "vendor:icims",        "label": "iCIMS",      "notes": "Iframe form. Resume upload via native picker. Auth wall mid-walk."},
    "myworkdayjobs.com": {"id": "vendor:workday",   "label": "Workday",    "notes": "Often account-gated; sometimes direct."},
}


def _load_graph() -> tuple[dict, dict, list]:
    """Returns (raw_graph, nodes_by_id, edges). Empty on any load failure."""
    try:
        g = json.loads(_GRAPH.read_text())
        nodes_by_id = {n["id"]: n for n in g["nodes"]}
        return g, nodes_by_id, g.get("edges", [])
    except Exception:
        return {}, {}, []


def _fixes_for_vendor(nodes_by_id: dict, edges: list, vendor_id: str) -> list[str]:
    """Traverse error→fix edges for all errors attributed to vendor_id."""
    g_nodes = list(nodes_by_id.values())
    error_ids = {
        n["id"] for n in g_nodes
        if n.get("type") == "error" and vendor_id in n.get("vendors", [])
    }
    hints = []
    for edge in edges:
        if edge["from"] in error_ids and edge.get("rel") == "FIXED_BY":
            fix = nodes_by_id.get(edge["to"])
            if fix and fix.get("description"):
                hints.append(fix["description"])
    return hints


def lookup(url: str) -> dict | None:
    """Return the vendor node dict (with fix_hints) if the URL matches a known ATS."""
    if not url:
        return None
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return None

    g, nodes_by_id, edges = _load_graph()

    vendor = None
    for n in nodes_by_id.values():
        if n.get("type") != "vendor":
            continue
        for pat in n.get("domains", []):
            if fnmatch.fnmatch(host, pat):
                vendor = n
                break
        if vendor:
            break

    if vendor is None:
        for substr, stub in _FALLBACK.items():
            if substr in host:
                vendor = stub
                break

    if vendor is None:
        return None

    # Enrich with cross-vendor fix hints
    vendor_id = vendor.get("id", "")
    if vendor_id and nodes_by_id:
        hints = _fixes_for_vendor(nodes_by_id, edges, vendor_id)
        if hints:
            return {**vendor, "fix_hints": hints}
    return vendor


def find_fixes(symptom: str) -> list[dict]:
    """Cross-vendor: find {error, fix} pairs whose symptom matches the hint.

    Use when the agent is stuck on an unknown vendor — search by what you observe
    (e.g. 'fill lands nowhere', 'shadow dom', 'iframe') to find the known fix.
    """
    if not symptom:
        return []
    needle = symptom.lower()
    g, nodes_by_id, edges = _load_graph()
    results = []
    for n in nodes_by_id.values():
        if n.get("type") != "error":
            continue
        if needle not in (n.get("symptom") or "").lower() and needle not in n["id"].lower():
            continue
        for edge in edges:
            if edge["from"] == n["id"] and edge.get("rel") == "FIXED_BY":
                fix = nodes_by_id.get(edge["to"])
                if fix:
                    results.append({"error": n, "fix": fix})
    return results
