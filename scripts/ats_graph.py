#!/usr/bin/env python3
"""Query / append the ATS knowledge graph (docs/career-agent/ats-graph.json).

Retrieval-first: `query(term)` returns only the matching nodes + their edges, so
a session pulls a small slice into context instead of the whole file. `add_node`
/ `add_edge` grow the graph. Superseded approaches stay (status="superseded")
with a SUPERSEDES edge, so older approaches are retained, not overwritten.

    python scripts/ats_graph.py query successfactors   # slice about SuccessFactors
    python scripts/ats_graph.py neighbors site:zf       # what ZF composes
"""
from __future__ import annotations
import json
from pathlib import Path

_G = Path(__file__).resolve().parents[1] / "docs" / "career-agent" / "ats-graph.json"


def load() -> dict:
    return json.loads(_G.read_text())


def save(g: dict) -> None:
    _G.write_text(json.dumps(g, indent=2) + "\n")


def query(term: str) -> dict:
    """Nodes whose id/label/attrs contain `term` (case-insensitive), plus every
    edge touching them. Returns a small slice, not the whole graph."""
    g = load()
    t = term.lower()
    nodes = [n for n in g["nodes"] if t in json.dumps(n).lower()]
    ids = {n["id"] for n in nodes}
    edges = [e for e in g["edges"] if e["from"] in ids or e["to"] in ids]
    return {"nodes": nodes, "edges": edges}


def neighbors(node_id: str) -> dict:
    """The node plus its directly-connected nodes/edges (1 hop)."""
    g = load()
    edges = [e for e in g["edges"] if e["from"] == node_id or e["to"] == node_id]
    ids = {node_id} | {e["from"] for e in edges} | {e["to"] for e in edges}
    nodes = [n for n in g["nodes"] if n["id"] in ids]
    return {"nodes": nodes, "edges": edges}


def add_node(node: dict) -> dict:
    """Upsert a node by id (replaces same id). To retire an approach, add the new
    node and set the old one's status='superseded' + an edge {rel:'SUPERSEDES'}."""
    g = load()
    g["nodes"] = [n for n in g["nodes"] if n["id"] != node["id"]] + [node]
    save(g)
    return {"nodes": len(g["nodes"]), "edges": len(g["edges"])}


def add_edge(edge: dict) -> dict:
    g = load()
    if edge not in g["edges"]:
        g["edges"].append(edge)
    save(g)
    return {"nodes": len(g["nodes"]), "edges": len(g["edges"])}


def _demo() -> None:
    # self-check: query returns a non-empty slice smaller than the whole graph
    g = load()
    res = query("successfactors")
    assert res["nodes"], "expected a match for successfactors"
    assert len(res["nodes"]) < len(g["nodes"]), "query should return a slice, not all"
    assert neighbors("site:zf")["edges"], "zf should have edges"
    print("ok:", len(g["nodes"]), "nodes", len(g["edges"]), "edges")


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 1 or sys.argv[1] == "demo":
        _demo()
    elif sys.argv[1] == "query":
        print(json.dumps(query(sys.argv[2]), indent=2))
    elif sys.argv[1] == "neighbors":
        print(json.dumps(neighbors(sys.argv[2]), indent=2))
    else:
        print(__doc__)
