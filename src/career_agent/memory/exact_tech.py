"""Exact Tech vault: verbatim pre-approved technical descriptions.

Source: data/answer_style/ingredients.json — one unit per project, each with a
`source` field that is the VERBATIM quote to copy into application answers.

Rule: EXACT_TECH_SEARCH returns the `source` text character-for-character.
Never paraphrase, summarise, or rephrase technical facts from this vault.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

_DEFAULT_PATH = (Path(__file__).resolve()
                 .parent.parent.parent.parent  # repo root
                 / "data" / "answer_style" / "ingredients.json")


def _load_units(path: Path) -> list[dict]:
    return json.loads(path.read_text()).get("units", [])


def _build_fts(conn: sqlite3.Connection, units: list[dict]) -> None:
    conn.execute(
        "CREATE VIRTUAL TABLE exact_tech_fts USING fts5(unit_id UNINDEXED, body)"
    )
    for u in units:
        tech = u.get("tech", "")
        if isinstance(tech, list):
            tech = " ".join(tech)
        body = " ".join(filter(None, [
            u.get("title", ""),
            u.get("org", ""),
            tech,
            " ".join(u.get("tags", [])),
            u.get("source", ""),
        ]))
        conn.execute("INSERT INTO exact_tech_fts VALUES (?, ?)", [u["id"], body])
    conn.commit()


class ExactTechVault:
    """In-memory FTS5 index over the ingredient bank. Rebuilt each instantiation
    (6 units — negligible). Inject `units_path` in tests to point at a fixture."""

    def __init__(self, units_path: Path = _DEFAULT_PATH):
        self._units = {u["id"]: u for u in _load_units(units_path)}
        self._conn = sqlite3.connect(":memory:")
        _build_fts(self._conn, list(self._units.values()))

    def search(self, keywords: str, limit: int = 3) -> list[dict]:
        """Return matching units. Each result carries the verbatim `source`.
        Copy source CHARACTER-FOR-CHARACTER — never paraphrase."""
        tokens = re.findall(r"[a-zA-Z0-9]+", keywords or "")
        if not tokens:
            return []
        query = " OR ".join(tokens)
        try:
            rows = self._conn.execute(
                "SELECT unit_id FROM exact_tech_fts "
                "WHERE body MATCH ? ORDER BY bm25(exact_tech_fts) LIMIT ?",
                [query, limit],
            ).fetchall()
        except Exception:
            return []
        out = []
        for (uid,) in rows:
            u = self._units.get(uid)
            if u:
                out.append({
                    "id": u["id"],
                    "title": u["title"],
                    "source": u["source"],   # VERBATIM — never paraphrase
                    "tags": u.get("tags", []),
                })
        return out
