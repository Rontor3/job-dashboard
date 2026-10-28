"""Crash-durable run trace — one append-only JSONL per run (triage O1).

<run_dir>/trace.jsonl lines: {"t": iso, "step": name, "status": start|done|error, **fields}.
Each start is written and fsynced BEFORE its step's risky work, so a mid-run crash cannot
lose what the run was doing when it died. Module-level singleton like page_prep._TRAIL —
one apply run per process; silence mode (_FILE None — no begin(), off(), or no usable dir)
makes every call a no-op, and write failures become one [trace] warning, never a run failure.
"""
from __future__ import annotations

import contextlib
import datetime
import json
import os
from functools import wraps

_FILE: str | None = None          # the run's trace.jsonl (None = silence: calls no-op)
_RUN_DONE = False                 # the "run" step closes once per process (main's finally)
_WARNED = False                   # a broken trace prints one [trace] warning, then goes quiet


def _warn(e: Exception) -> None:
    global _WARNED
    if not _WARNED:
        _WARNED = True
        print(f"[trace] recording disabled ({type(e).__name__}: {e})", flush=True)


def _emit(status: str, step: str, **fields) -> None:
    """Append one JSON line, fsynced; never raises — a broken trace must not kill a run."""
    if _FILE is None:
        return
    try:
        with open(_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": datetime.datetime.utcnow().isoformat(),
                                 "step": step, "status": status, **fields},
                                default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())     # the start of a risky step must already be on disk
    except Exception as e:
        _warn(e)


def begin(run_dir) -> None:
    """Point the trace at this run's artifact dir (the screenshots' own run_dir). None,
    or an uncreatable dir, leaves the whole run in silence mode."""
    global _FILE, _RUN_DONE
    _FILE, _RUN_DONE = None, False
    if not run_dir:
        return
    try:
        os.makedirs(str(run_dir), exist_ok=True)    # agent_runs/<job>/ may not exist yet
        path = os.path.join(str(run_dir), "trace.jsonl")
        open(path, "a", encoding="utf-8").close()   # exists from run start; an append never truncates
        _FILE = path
    except Exception as e:
        _warn(e)


def off() -> None:
    """Silence mode for tests/REPL: every writer no-ops (and the warn latch resets)."""
    global _FILE, _WARNED
    _FILE, _WARNED = None, False


def start(step: str, **fields) -> None:
    """Open a trace step — durable before the risky work beneath it."""
    _emit("start", step, **fields)


def end(step: str, status: str = "done", **fields) -> None:
    """Close a trace step. "done" = clean outcome (stopped_reason carries it); "error" = exception."""
    if step == "run":                 # one run-end per process: the error record beats main's finally
        global _RUN_DONE
        if _RUN_DONE:
            return
        _RUN_DONE = True
    _emit(status, step, **fields)


@contextlib.contextmanager
def step(name: str, **fields):
    """start → body → end; a body exception records error, then re-raises."""
    start(name, **fields)
    try:
        yield
    except BaseException as e:
        end(name, "error", error=f"{type(e).__name__}: {e}"[:200])
        raise
    end(name, "done")


def traced(name: str):
    """Decorator form of step(): around each call of a graph node function."""
    def deco(fn):
        @wraps(fn)
        def run(*a, **k):
            with step(name):
                return fn(*a, **k)
        return run
    return deco
