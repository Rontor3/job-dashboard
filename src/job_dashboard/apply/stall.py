"""Stall watchdog for apply-queue runs: if a run makes no progress for N minutes, stop it so the
queue moves on. Progress = what the agent is actually filling or reaching, read from its log — not
mere log growth, so a loop that keeps printing the same snapshot still counts as stalled."""
from __future__ import annotations

import os
import re
import time

STALL_EXIT = 124                                  # exit code reported for a run stopped as stalled
STALL_S = int(float(os.getenv("CAREER_AGENT_STALL_MINUTES", "10")) * 60)

_FILLED = re.compile(r"\[fill\] (?:step|screen) \d+: (\d+) (?:filled|decisions)")
_PAGE = re.compile(r"\[perc\] frame 0: '([^']*)'")
_ASSIST = re.compile(r"\[assist \d+/\d+\] Claude chose: (?!give_up|invalid)")
_ASKED = re.compile(r"\[telegram\] sending \d+ field question")      # a question went to the human: the clock restarts
_ANSWERED = re.compile(r"\[human\] got \d+ answer")                # the human replied: that is progress too


def progress_token(log: str) -> tuple:
    """Changes only when the run fills more fields, reaches a new page, acts on Claude's help, asks the human a question
    or receives their answer (waiting on a person is not a stall until they have had their time)."""
    filled = max((int(n) for n in _FILLED.findall(log)), default=0)
    return (filled, len(set(_PAGE.findall(log))), len(_ASSIST.findall(log)),
            len(_ASKED.findall(log)), len(_ANSWERED.findall(log)))


def _tail(path: str, max_bytes: int = 262144) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - max_bytes))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def watch(is_running, stop, log_path: str, stall_s: int = STALL_S, poll_s: float = 5.0,
          clock=time.monotonic, sleep=time.sleep, say=print) -> bool:
    """Block while the run is alive. Returns True if it was stopped for stalling, False if it exited."""
    token, last_change = progress_token(_tail(log_path)), clock()
    while is_running():
        sleep(poll_s)
        now = progress_token(_tail(log_path))
        if now != token:
            say(f"[queue] progress: filled={now[0]} pages={now[1]} assist={now[2]}", flush=True)
            token, last_change = now, clock()
        elif clock() - last_change >= stall_s:
            say(f"[queue] no progress for {stall_s // 60} min (filled={token[0]}, pages={token[1]}) — "
                "stopping this run and moving to the next job", flush=True)
            stop()
            return True
    return False
