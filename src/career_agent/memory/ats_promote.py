"""Fold pending-memory run trails into the ATS knowledge graph (docs/career-agent/ats-graph.json).

Deterministic, no LLM: each run block that carries a `- trail:` line is grouped by the host the
run started on. That host's `site:<host>` node gets the latest *successful* reach path (a run that
ended with no stopped_reason), the set of errors seen, and a ROUTES_TO edge to the host it landed on.
Promoted blocks move to pending_memory_promoted.md, so the same page isn't relearned each run.
Runs without a trail (older entries) are left in place.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

_ROOT = Path(__file__).resolve().parents[3]
GRAPH = _ROOT / "docs" / "career-agent" / "ats-graph.json"
PENDING = _ROOT / "data" / "pending_memory_updates.md"


def _host(u: str) -> str:
    h = urlparse(u if "//" in u else f"//{u}").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _field(block: str, key: str):
    m = re.search(rf"^- {key}: (.*)$", block, re.M)
    return m.group(1).strip() if m else None


def _site(nodes: dict, host: str) -> dict:
    """The graph's existing node for this host (matched on its `domains`), else a new site:<host>."""
    for n in nodes.values():
        if n.get("type") == "site" and any(host == d or host.endswith("." + d) for d in n.get("domains", [])):
            return n
    return nodes.setdefault(f"site:{host}", {"id": f"site:{host}", "type": "site", "label": host, "domains": [host]})


def _clicks(trail: list) -> list[str]:
    return [e["click"] for e in trail if e.get("step") == "hop"]


def _path(trail: list) -> list[str]:
    out = []
    for e in trail:
        st = e.get("step")
        if st == "hop":
            out.append(f"click {e['role']} '{e['click']}' (frame {e['frame']}) -> {e['url_after']}")
        elif st == "modal_kept":
            out.append(f"modal kept open ({e['why']})")
        elif st == "modal_dismissed":
            out.append(f"modal dismissed via '{e['via']}'")
        elif st == "url_variant":
            out.append(f"url variant -> {e['url_after']}")
    return out


def promote(pending: Path = PENDING, graph: Path = GRAPH) -> dict:
    """Returns {"promoted": n, "sites": [node ids]}; never raises on a missing file."""
    if not pending.exists() or not graph.exists():
        return {"promoted": 0, "sites": []}
    parts = re.split(r"(?m)^(?=## Run )", pending.read_text())
    keep, done, by_site = [parts[0]], [], {}
    for blk in parts[1:]:
        raw = _field(blk, "trail")
        if raw is None:
            keep.append(blk)
            continue
        try:
            trail = json.loads(raw)
        except ValueError:
            keep.append(blk)
            continue
        done.append(blk)
        entry, landed = _host(_field(blk, "URL") or ""), _host(_field(blk, "landed") or "")
        by_site.setdefault(entry, []).append({
            "reason": _field(blk, "stopped_reason") or "None", "landed": landed, "path": _path(trail), "clicks": _clicks(trail),
            "end": next((e.get("status") for e in reversed(trail) if e.get("step") == "reach_end"), None)})
    if not done:
        return {"promoted": 0, "sites": []}

    g = json.loads(graph.read_text())
    nodes = {n["id"]: n for n in g["nodes"]}
    for host, runs in by_site.items():
        node = _site(nodes, host)
        nid = node["id"]
        errs = set(node.get("errors_seen", [])) | {r["reason"] for r in runs if r["reason"] != "None"}
        node["errors_seen"] = sorted(errs)
        good = [r for r in runs if r["reason"] == "None" and r["path"]]
        if good:                                      # latest successful run defines the known-good path
            node["reach_path"], node["lands_on"] = good[-1]["path"], good[-1]["landed"]
            node["reach_clicks"] = good[-1]["clicks"]
            node["reach_end"] = good[-1]["end"]
            if good[-1]["landed"] and good[-1]["landed"] != host:
                edge = {"from": nid, "to": _site(nodes, good[-1]["landed"])["id"], "rel": "ROUTES_TO"}
                if edge not in g["edges"]:
                    g["edges"].append(edge)
    g["nodes"] = list(nodes.values())
    graph.write_text(json.dumps(g, indent=2, ensure_ascii=False) + "\n")
    with open(pending.with_name("pending_memory_promoted.md"), "a") as fh:
        fh.write("".join(done))
    pending.write_text("".join(keep))
    return {"promoted": len(done), "sites": [_site(nodes, h)["id"] for h in by_site]}


if __name__ == "__main__":
    print(promote())
