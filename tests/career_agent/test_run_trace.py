"""run_trace (triage O1): crash-durable step pairs in <run_dir>/trace.jsonl.

Covers the durability contract (start on disk before the risky work), the
exception -> error record, silence mode, append-not-truncate across reruns, and
the replay vocabulary a real run writes through apply.py / boards/run.py hooks.
"""
import json

import pytest

from career_agent import run_trace


@pytest.fixture(autouse=True)
def _silence_between_tests():
    yield
    run_trace.off()


def _lines(run_dir):
    return [json.loads(l) for l in (run_dir / "trace.jsonl").read_text().strip().splitlines()]


def test_begin_creates_the_trace_file_at_run_start(tmp_path):
    run_trace.begin(str(tmp_path / "agent_runs" / "41"))
    assert (tmp_path / "agent_runs" / "41" / "trace.jsonl").exists()
    assert _lines(tmp_path / "agent_runs" / "41") == []          # created, not written


def test_start_is_durable_on_disk_before_the_step_completed(tmp_path):
    run_trace.begin(str(tmp_path))
    run_trace.start("board_run", board="naukri")
    # crash-point: even if the run died RIGHT here, the step's start is already on disk
    first = _lines(tmp_path)[0]
    assert first["status"] == "start" and first["step"] == "board_run"
    assert first["board"] == "naukri" and first["t"], first      # iso timestamp in every record
    run_trace.end("board_run", "done", stopped_reason="stuck")
    assert [r["status"] for r in _lines(tmp_path)] == ["start", "done"]
    assert _lines(tmp_path)[1]["stopped_reason"] == "stuck"


def test_an_exception_in_a_step_records_error_then_re_raises(tmp_path):
    run_trace.begin(str(tmp_path))
    with pytest.raises(RuntimeError):
        with run_trace.step("initial_load", url="https://x.example"):
            raise RuntimeError("tab vanished")
    lines = _lines(tmp_path)
    assert [r["status"] for r in lines] == ["start", "error"]
    assert lines[1]["step"] == "initial_load" and "tab vanished" in lines[1]["error"]


def test_silence_mode_makes_every_call_a_no_op(tmp_path):
    run_trace.off()
    run_trace.start("initial_load")
    run_trace.end("run", "done", stopped_reason="closed")
    with run_trace.step("board_run"):
        pass
    run_trace.begin(None)                       # a run with no resolvable dir traces nowhere
    run_trace.start("initial_load")
    run_trace.end("run", "done")
    assert list(tmp_path.rglob("*")) == []


def test_a_rerun_appends_but_never_erases_a_crash_trace(tmp_path):
    run_trace.begin(str(tmp_path))
    run_trace.start("board_run", board="naukri")             # the run died before its end
    crash_tail = _lines(tmp_path)
    run_trace.begin(str(tmp_path))                           # the same job re-runs later
    run_trace.start("board_run", board="naukri")
    run_trace.end("board_run", "done", stopped_reason="needs_human")
    lines = _lines(tmp_path)
    assert len(lines) == 3                                   # the crash record came through
    assert lines[0] == crash_tail[0] and lines[0]["status"] == "start"
    assert lines[-1]["stopped_reason"] == "needs_human"


def test_a_board_run_records_the_replay_vocabulary(tmp_path):
    """The hook sequence apply.py / boards/run.py / graph.py record — the trace
    file is the replay vocabulary (step names are stable snake_case)."""
    run_dir = tmp_path / "agent_runs" / "41"
    run_trace.begin(str(run_dir))

    @run_trace.traced("perceive")
    def _perceive():                             # graph.py's decorate-around-the-node pass
        return {}

    run_trace.start("run", job_id=41)            # apply.py main, after begin(run_dir)
    with run_trace.step("initial_load"):
        pass                                     # apply.py around the first page load
    run_trace.start("board_run", board="naukri", probe=False)  # boards/run.py run_board entry
    run_trace.start("entry_chain", legs=2)
    run_trace.end("entry_chain", "done")
    run_trace.start("wall_check")
    run_trace.end("wall_check", "done", outcome="cleared")
    _perceive()
    run_trace.start("perceive_fields")
    run_trace.end("perceive_fields", "done", fields=3, sensitive=0)
    run_trace.start("ask", asked=1)
    run_trace.end("ask", "done", given=1, asked=1)
    run_trace.end("board_run", "done", stopped_reason="needs_human")  # boards/run.py stop()
    run_trace.end("run", "done", stopped_reason="needs_human")        # apply.py finally
    recs = _lines(run_dir)
    assert [r["step"] for r in recs] == [
        "run", "initial_load", "initial_load", "board_run",
        "entry_chain", "entry_chain", "wall_check", "wall_check",
        "perceive", "perceive", "perceive_fields", "perceive_fields",
        "ask", "ask", "board_run", "run"]
    assert all(r["t"][:4].isdigit() for r in recs)          # every event is timestamped
    assert recs[-2]["stopped_reason"] == "needs_human" and recs[-1]["status"] == "done"


def test_the_run_step_records_one_end_even_after_an_error_end(tmp_path):
    run_trace.begin(str(tmp_path))
    run_trace.end("run", "error", error="boom")              # main()'s except path
    run_trace.end("run", "done", stopped_reason="error")     # main()'s finally: no duplicate
    assert [r["status"] for r in _lines(tmp_path)] == ["error"]


def test_an_uncreatable_dir_degrades_to_silence_with_one_warning(tmp_path, capsys):
    blocker = tmp_path / "blocked.txt"
    blocker.write_text("not a directory")
    run_trace.begin(str(blocker / "agent_runs" / "9"))
    run_trace.start("initial_load")
    run_trace.end("run", "done")
    assert blocker.read_text() == "not a directory"          # the trace never touched the run
    assert capsys.readouterr().out.count("[trace]") == 1


def test_a_broken_disk_writes_one_warning_and_never_raises(tmp_path, monkeypatch, capsys):
    run_trace.begin(str(tmp_path))

    def boom(fd):
        raise OSError(-9, "bad descriptor")

    monkeypatch.setattr(run_trace.os, "fsync", boom)
    run_trace.start("entry_chain", legs=1)
    run_trace.end("entry_chain", "error")
    run_trace.start("ask")                                   # each failure warned once, total
    assert capsys.readouterr().out.count("[trace]") == 1
