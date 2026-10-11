"""What the change log can write back on Undo: one reader and writer per kind of data (see changes.py).

    profile      application_profile column            entity_id "1", field = column
    qbank        question-bank entry answer / status    entity_id = entry id, field "answer" | "status"
    qa_row       one application question's answer      entity_id = application_qa id, field "answer"
    setting      agent_settings value                   entity_id = key, field "value"
    config       config table value                     entity_id = key, field "value"
    job          jobs.status / apply_details            entity_id = job id, field "status" | "apply_details"
    company      details for every opening at a company  entity_id = company name, field "details"
    file         a whole text file under our control   entity_id = name in FILES, field "text" (None = absent)
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from job_dashboard import changes, company_details, paths, qa_store


def candidate_profile_path() -> Path:
    from job_dashboard.match.profile_text import PROFILE_FILE
    return PROFILE_FILE.with_suffix(".local" + PROFILE_FILE.suffix)


FILES = {
    "candidate_profile": candidate_profile_path,
    "setup_state": lambda: paths.DATA_DIR / "setup-state.md",
    "ingredients": lambda: paths.INGREDIENTS,
    "about_me": lambda: paths.ABOUT_ME,
}


def read_file(name: str) -> str | None:
    p = FILES[name]()
    return p.read_text(encoding="utf-8") if p.is_file() else None


def write_file(name: str, text: str | None) -> None:
    p = FILES[name]()
    if text is None:
        p.unlink(missing_ok=True)
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".", suffix=".tmp")     # unique: writers may overlap
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, p)


def _profile_read(conn, _id, fld):
    from job_dashboard.apply.store import _PROFILE_COLS, get_application_profile
    if fld not in _PROFILE_COLS:
        raise KeyError(fld)
    return (get_application_profile(conn) or {}).get(fld)


def _profile_write(conn, _id, fld, value):
    from job_dashboard.apply.store import get_application_profile, save_application_profile
    save_application_profile(conn, {**(get_application_profile(conn) or {}), fld: value})


def _qbank_read(conn, entry_id, fld):
    from career_agent.memory import qbank
    e = qbank.get_entry(conn, entry_id)
    return None if e is None else e[fld]


def _qbank_write(conn, entry_id, fld, value):
    from career_agent.memory import qbank
    if fld == "answer":
        qbank.set_answer(conn, entry_id, value)
    else:
        qbank.set_status(conn, entry_id, value or "superseded")    # a created entry's "before" is None: retire it


def _qa_read(conn, row_id, _fld):
    row = conn.execute("SELECT answer, status FROM application_qa WHERE id=?", (row_id,)).fetchone()
    return None if row is None else {"answer": row[0], "status": row[1]}


def _qa_write(conn, row_id, _fld, value):
    value = value or {"answer": None, "status": "needs_answer"}
    conn.execute("UPDATE application_qa SET answer=?, status=?, updated_at=? WHERE id=?",
                 (value["answer"], value["status"], qa_store._now(), row_id))
    conn.commit()


def _setting_write(conn, key, _fld, value):
    qa_store.set_setting(conn, key, value)


def _config_read(_conn, key, _fld):
    from job_dashboard import config
    return config.stored().get(key)


def _config_write(_conn, key, _fld, value):
    from job_dashboard import config
    config.put(key, value or "")


def _job_read(conn, job_id, fld):
    if fld == "priority":
        from job_dashboard.apply import run_store
        run_store.ensure(conn)
        row = conn.execute("SELECT priority FROM jobs WHERE id=?", (job_id,)).fetchone()
        return None if row is None else row[0]
    if fld == "status":
        row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        return None if row is None else row[0]
    row = conn.execute("SELECT apply_details FROM jobs WHERE id=?", (job_id,)).fetchone()
    return json.loads(row[0]) if row and row[0] else {}


def _job_write(conn, job_id, fld, value):
    from job_dashboard.db import set_apply_details, set_job_status
    if fld == "priority":
        from job_dashboard.apply import run_store
        if value is None:
            conn.execute("UPDATE jobs SET priority=NULL WHERE id=?", (int(job_id),))
            conn.commit()
        else:
            run_store.set_priority(conn, int(job_id), value)
    elif fld == "status":
        set_job_status(conn, int(job_id), value)
    else:
        set_apply_details(conn, int(job_id), value or {})


changes.register("profile", _profile_read, _profile_write)
changes.register("qbank", _qbank_read, _qbank_write)
changes.register("qa_row", _qa_read, _qa_write)
changes.register("setting", lambda conn, key, _f: qa_store.get_setting(conn, key), _setting_write)
changes.register("config", _config_read, _config_write)
changes.register("job", _job_read, _job_write)
changes.register("company", lambda conn, name, _f: company_details.get(conn, name),
                 lambda conn, name, _f, v: company_details.put(conn, name, v))
changes.register("file", lambda _c, name, _f: read_file(name), lambda _c, name, _f, v: write_file(name, v))
