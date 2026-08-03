from job_dashboard.db import init_db
from job_dashboard.apply.store import (
    get_application_profile, save_application_profile,
    save_application, get_application, set_application_status,
)


def _conn(tmp_path):
    return init_db(str(tmp_path / "t.db"))


def test_profile_unset_is_none_then_roundtrips(tmp_path):
    c = _conn(tmp_path)
    assert get_application_profile(c) is None
    saved = save_application_profile(c, {
        "full_name": "Rakshit Singh", "email": "r@x.com", "phone": "123",
        "work_authorization": "US: needs sponsorship, no H1B", "willing_to_relocate": True,
    })
    assert saved["full_name"] == "Rakshit Singh"
    got = get_application_profile(c)
    assert got["email"] == "r@x.com" and got["willing_to_relocate"] in (True, 1)


def test_profile_upsert_updates_single_row(tmp_path):
    c = _conn(tmp_path)
    save_application_profile(c, {"full_name": "A", "email": "a@x.com"})
    save_application_profile(c, {"full_name": "B", "email": "b@x.com"})
    got = get_application_profile(c)
    assert got["full_name"] == "B"  # still one row, updated


def test_application_roundtrip_cover_letter_optional(tmp_path):
    c = _conn(tmp_path)
    aid = save_application(c, job_id=7, resume_id=3, cover_letter_id=None,
                           screening=[{"question": "Why us?", "answer": "Because X"}],
                           ats="greenhouse", status="prepared")
    got = get_application(c, 7)
    assert got["id"] == aid and got["cover_letter_id"] is None
    assert got["resume_id"] == 3 and got["ats"] == "greenhouse"
    assert got["screening"][0]["question"] == "Why us?"
    set_application_status(c, aid, "applied", applied_at="2026-07-31T00:00:00Z")
    assert get_application(c, 7)["status"] == "applied"


def test_get_application_unknown_job_is_none(tmp_path):
    assert get_application(_conn(tmp_path), 999) is None


def test_profile_roundtrips_naukri_ctc_and_reason(tmp_path):
    import sqlite3
    from job_dashboard.apply.store import (
        ensure_application_tables, save_application_profile, get_application_profile)
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    ensure_application_tables(conn)
    save_application_profile(conn, {
        "full_name": "Rakshit Singh",
        "current_ctc": "12 LPA",
        "reason_for_change": "Seeking deeper ML ownership",
    })
    p = get_application_profile(conn)
    assert p["current_ctc"] == "12 LPA"
    assert p["reason_for_change"] == "Seeking deeper ML ownership"


def test_add_column_guard_is_idempotent_on_existing_db(tmp_path):
    import sqlite3
    from job_dashboard.apply.store import ensure_application_tables
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    ensure_application_tables(conn)
    ensure_application_tables(conn)  # second call must not raise
    cols = {r[1] for r in conn.execute("PRAGMA table_info(application_profile)")}
    assert {"current_ctc", "reason_for_change"} <= cols
