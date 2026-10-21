"""O3 CLI hardening + O4 quota ladder: a broken/quota-capped `claude` CLI degrades, never kills the run.

O3: `_run_cli` maps the EPIPE family to stable reasons; recover() turns them into no action, and the dead
end falls through to its existing stop path. O4: a usage-limit reply persists `assist_cap_until` in the
jobs.db `agent_settings` table (plain SQL, table owned by the dashboard's qa_store) so later dead ends skip
Claude with ZERO calls until the 60-minute TTL passes.
"""
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from career_agent.longform import research as R
from career_agent.memory import facts as F
from career_agent.orchestrator import claude_assist as CA
from career_agent.orchestrator.claude_assist import ClaudeAssist


class _Page:                              # same stand-in as test_claude_assist.py
    url = "https://site.example/job"
    frames = []

    def __init__(self): self.went_back = 0
    def screenshot(self, path): open(path, "wb").write(b"x")
    def go_back(self): self.went_back += 1
    def wait_for_timeout(self, ms): pass


def _completed(rc, stdout="", stderr=""):
    return subprocess.CompletedProcess(["claude"], rc, stdout=stdout, stderr=stderr)


# ── O3: the hardened call and its stable reasons ─────────────────────────────────────────────

def test_run_cli_maps_hard_failures_to_stable_reasons(monkeypatch):
    def booms(exc):
        return lambda *a, **k: (_ for _ in ()).throw(exc)
    monkeypatch.setattr(subprocess, "run", booms(BrokenPipeError(32)))
    assert CA._run_cli("x") == (None, "epipe")
    monkeypatch.setattr(subprocess, "run", booms(subprocess.TimeoutExpired("claude", 120)))
    assert CA._run_cli("x") == (None, "timeout")
    monkeypatch.setattr(subprocess, "run", booms(FileNotFoundError()))
    assert CA._run_cli("x") == (None, "cli_missing")
    monkeypatch.setattr(subprocess, "run", booms(OSError(5)))
    assert CA._run_cli("x") == (None, "os_error")


def test_run_cli_never_lets_a_failure_escape_through_a_quota_timer(monkeypatch):
    """A timeout can also be the quota refusing the call: its partial output carries the limit line."""
    def booms(exc):
        return lambda *a, **k: (_ for _ in ()).throw(exc)
    monkeypatch.setattr(subprocess, "run", booms(
        subprocess.TimeoutExpired("claude", 120, output=b"You've hit your weekly limit")))
    assert CA._run_cli("x") == (None, "quota")


def test_run_cli_reads_the_limit_markers_off_stdout_and_stderr(monkeypatch):
    def says(rc, out, err):
        return lambda *a, **k: _completed(rc, out, err)
    for rc, out, err in ((1, "", "You've hit your weekly limit"), (0, "", "5-hour limit reached"),
                         (1, "limit reached", "x")):
        monkeypatch.setattr(subprocess, "run", says(rc, out, err))
        assert CA._run_cli("x") == (None, "quota")
    monkeypatch.setattr(subprocess, "run", says(1, "", "boom"))
    assert CA._run_cli("x") == (None, "cli_error")
    monkeypatch.setattr(subprocess, "run", says(0, "", ""))
    assert CA._run_cli("x") == (None, "empty")


def test_run_cli_keeps_healthy_output_untouched(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed(0, '{"action":"go_back"}'))
    assert CA._run_cli("x") == ('{"action":"go_back"}', None)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed(1, "some prose"))
    assert CA._run_cli("x") == ("some prose", None)          # exit != 0 but usable stdout: as before


def test_claude_cli_wrapper_keeps_its_fatal_contract_but_typed(monkeypatch):
    def boom(*a, **k): raise BrokenPipeError(32)
    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="epipe"):
        CA._claude_cli("x")


# ── O3: recover() degrades; the run survives every CLI failure ─────────────────────────────────

def test_recover_degrades_to_no_action_on_every_cli_failure(tmp_path):
    for why in ("epipe", "timeout", "cli_missing", "os_error", "cli_error", "empty", "quota"):
        a = ClaudeAssist(run=lambda p, t=120, w=why: (None, w), shot_dir=str(tmp_path))
        p = _Page()
        assert a.recover(p, "stuck") is False                # no exception out of recover, ever
        assert a.calls == 1 and p.went_back == 0             # one call spent; the dead end fell through


def test_the_hardened_helper_is_the_default_run():
    assert ClaudeAssist(shot_dir="/tmp")._run is CA._run_cli


def test_recover_still_acts_on_a_healthy_reply(tmp_path):
    a = ClaudeAssist(run=lambda p, t=120: ('{"action":"go_back"}', None), shot_dir=str(tmp_path))
    p = _Page()
    assert a.recover(p, "stuck") is True and p.went_back == 1


# ── O4: the quota ladder — detect, persist, short-circuit, expire ──────────────────────────────

def _db(tmp_path) -> str:
    p = tmp_path / "jobs.db"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE agent_settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()
    return str(p)


def _setting(db):
    conn = sqlite3.connect(db)
    try:
        row = conn.execute("SELECT value FROM agent_settings WHERE key='assist_cap_until'").fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None


def test_a_quota_reply_persists_the_cap_and_the_next_dead_end_skips_claude(tmp_path, capsys):
    db = _db(tmp_path)
    seen = []

    def fail_quota(prompt, timeout=120):
        seen.append(prompt)
        return None, "quota"

    p = _Page()
    a = ClaudeAssist(run=fail_quota, shot_dir=str(tmp_path), db_path=db)
    assert a.recover(p, "stuck") is False                    # the capped dead end still stops normally
    assert len(seen) == 1 and _setting(db)                   # cap state lives in agent_settings
    saved = datetime.fromisoformat(_setting(db))
    assert timedelta(minutes=59, seconds=30) < saved - CA._now() <= timedelta(minutes=60)
    assert a.recover(p, "stuck") is False
    assert len(seen) == 1                                    # second dead end: ZERO claude calls while capped
    out = capsys.readouterr().out
    assert "[assist] capped until" in out and "stuck proceeds without assist" in out


def test_the_cap_expires_after_its_ttl_and_claude_is_asked_again(tmp_path, monkeypatch):
    db = _db(tmp_path)
    base = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(CA, "_now", lambda: base)
    seen = []
    a = ClaudeAssist(run=lambda p, t=120: (seen.append(p) or (None, "quota")), shot_dir=str(tmp_path), db_path=db)
    p = _Page()
    a.recover(p, "stuck") and a.recover(p, "stuck")
    assert len(seen) == 1                                    # first call spent detecting, second short-circuited
    monkeypatch.setattr(CA, "_now", lambda: base + timedelta(minutes=61))
    assert CA._cap_until(db) is None                         # expired
    assert a.recover(p, "stuck") is False and len(seen) == 2 # the call is made again (still quota, so re-capped)


def test_a_missing_settings_table_never_breaks_the_ladder(tmp_path):
    db = str(tmp_path / "empty_jobs.db")                     # sqlite creates the file with NO agent_settings
    seen = []
    a = ClaudeAssist(run=lambda p, t=120: (seen.append(p) or (None, "quota")), shot_dir=str(tmp_path), db_path=db)
    p = _Page()
    assert a.recover(p, "stuck") is False                    # degrade, never crash on the settings write
    assert a.recover(p, "stuck") is False                    # nothing persisted -> NOT capped
    assert len(seen) == 2 and _setting(db) is None


def test_assist_without_a_db_is_ladder_free(tmp_path):
    seen = []
    a = ClaudeAssist(run=lambda p, t=120: (seen.append(p) or (None, "quota")), shot_dir=str(tmp_path))
    p = _Page()
    assert a.recover(p, "stuck") is False and a.recover(p, "stuck") is False
    assert len(seen) == 2                                    # no cap state can exist without jobs.db


def test_a_healthy_claude_never_touches_cap_state(tmp_path):
    db = _db(tmp_path)
    a = ClaudeAssist(run=lambda p, t=120: ('{"action":"click","index":0}', None), shot_dir=str(tmp_path), db_path=db)
    a._controls = lambda page, limit=60: []                  # no controls -> click invalid, still a healthy reply
    p = _Page()
    assert a.recover(p, "stuck") is False                    # the normal refuse path, unchanged
    assert _setting(db) is None                              # and no cap was written


# ── the mirrors: facts and research degrade on the same family ─────────────────────────────────

def test_facts_llm_turns_the_epipe_family_into_the_planned_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(BrokenPipeError(32)))
    llm = F.claude_cli_llm()
    with pytest.raises(RuntimeError, match="epipe"):
        llm("prompt")
    assert F.compile_question("Rate your Selenium", "choice", ["1-3 years"], {}, {}, llm) == {}
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("c", 120)))
    with pytest.raises(RuntimeError, match="timeout"):
        llm("prompt")


def test_research_lookups_keep_their_empty_contract_and_name_the_reason(monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(BrokenPipeError(32)))
    assert R.haiku_lookup("Acme", "Engineer") == []
    assert "(epipe)" in capsys.readouterr().out
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("c", 180)))
    assert R.haiku_lookup("Acme", "Engineer") == []          # unchanged: no research is an empty bundle
