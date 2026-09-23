import sqlite3
import pytest
from career_agent.memory.factual_core import export_profile, load_profile
from job_dashboard.apply.store import (
    ensure_application_tables, save_application_profile,
)


def _seed_conn():
    conn = sqlite3.connect(":memory:")
    ensure_application_tables(conn)
    save_application_profile(conn, {
        "full_name": "Test User", "email": "t@example.com",
        "phone": "+1-555-0100", "work_authorization": "US Citizen",
        "notice_period": "2 weeks", "willing_to_relocate": True,
    })
    return conn


def test_export_then_load_roundtrip(tmp_path):
    conn = _seed_conn()
    path = tmp_path / "profile.json"
    exported = export_profile(conn, str(path))
    assert exported["full_name"] == "Test User"
    loaded = load_profile(str(path))
    assert loaded["email"] == "t@example.com"
    assert loaded["work_authorization"] == "US Citizen"
    assert loaded["willing_to_relocate"] is True


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_profile(str(tmp_path / "nope.json"))


# ── get_profile_chunk ──────────────────────────────────────────────────────────

from career_agent.memory.factual_core import get_profile_chunk

_PROFILE = {"personal": {"name": "Rakshit"}, "skills": ["Python", "SQL"]}


def test_get_profile_chunk_known_section():
    result = get_profile_chunk(_PROFILE, "personal")
    assert result == {"personal": {"name": "Rakshit"}}


def test_get_profile_chunk_other_section():
    result = get_profile_chunk(_PROFILE, "skills")
    assert result == {"skills": ["Python", "SQL"]}


def test_get_profile_chunk_missing_section_lists_available():
    with pytest.raises(KeyError) as exc:
        get_profile_chunk(_PROFILE, "missing")
    assert "missing" in str(exc.value)
    assert "personal" in str(exc.value) or "skills" in str(exc.value)
