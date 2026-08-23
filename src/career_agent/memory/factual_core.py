"""Factual Core: the agent's static, verbatim profile facts.

Sourced once from the dashboard's application_profile, then read from a
local JSON file. No LLM ever regenerates these values.
"""
from __future__ import annotations

import json
from pathlib import Path

from job_dashboard.apply.store import get_application_profile


def export_profile(conn, path: str) -> dict:
    profile = get_application_profile(conn)
    if profile is None:
        raise ValueError("no application_profile row (id=1) to export")
    profile.pop("updated_at", None)
    Path(path).write_text(json.dumps(profile, indent=2, sort_keys=True))
    return profile


def load_profile(path: str) -> dict:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"profile JSON not found: {path}")
    return json.loads(p.read_text())
