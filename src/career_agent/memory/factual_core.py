"""Factual Core: the agent's static, verbatim profile facts.

Sourced once from the dashboard's application_profile, then read from a
local JSON file. No LLM ever regenerates these values.
"""
from __future__ import annotations

import json
from pathlib import Path


def export_profile(conn, path: str) -> dict:
    # Imported lazily: the runtime read path (load_profile) must not depend on
    # the dashboard package — only this one-time export does.
    from job_dashboard.apply.store import get_application_profile

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


def get_profile_chunk(profile: dict, section: str) -> dict:
    """Return one section of the profile dict (JIT chunk for the memory router).
    Raises KeyError with available sections listed if the section is missing."""
    if section not in profile:
        raise KeyError(
            f"section {section!r} not in profile; available: {sorted(profile)}"
        )
    return {section: profile[section]}
