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
