"""Facade the run loop talks to: approvals and remote-solve. Keeps the run
loop ignorant of Telegram/CDP details, and degrades safely when remote solve
is not configured."""
from __future__ import annotations

from typing import NamedTuple


class RemoteSolveResult(NamedTuple):
    """``sent`` = the Telegram live-view link was actually dispatched.
    ``resolved`` = the human cleared the gate before the deadline.
    Truthy/falsy exactly like the old bare bool (``resolved``), so existing
    ``if human.remote_solve(...)`` callers are unaffected; run history can
    additionally inspect ``.sent`` to tell "never notified" apart from
    "notified but not solved in time"."""
    sent: bool
    resolved: bool

    def __bool__(self) -> bool:
        return self.resolved


class HumanLoop:
    def __init__(self, approver, remote_solve_factory=None, deadline_s: int = 900, collector=None):
        self.approver = approver
        self.remote_solve_factory = remote_solve_factory
        self.deadline_s = deadline_s
        self.collector = collector

    def approve(self, card: str) -> bool:
        return self.approver.request(card)

    def remote_solve(self, page, gate: str, on_link) -> RemoteSolveResult:
        if self.remote_solve_factory is None:
            return RemoteSolveResult(sent=False, resolved=False)  # caller degrades to Phase-1 stop-and-report
        # Any failure to stand up the live view (CDP error, port bind, a
        # public-host build_url refusal) must degrade to stop-and-report, never
        # crash the run — the gate stays escalated and nothing is submitted.
        session = None
        sent = False
        try:
            try:
                session = self.remote_solve_factory(page, gate)   # gate-aware factory
            except TypeError:
                session = self.remote_solve_factory(page)          # legacy single-arg
            on_link(session.start())
            sent = True
            resolved = bool(session.wait_until_cleared(self.deadline_s))
            return RemoteSolveResult(sent=True, resolved=resolved)
        except Exception as _e:
            import traceback
            print(f"[remote-solve] exception: {_e!r}", flush=True)
            traceback.print_exc()
            return RemoteSolveResult(sent=sent, resolved=False)
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    def collect(self, fields) -> dict:
        if self.collector is None or not fields:
            return {}
        return dict(self.collector(fields) or {})

    def get_events(self) -> dict:
        """Return {ref: 'approve'|'edit'} from the last collect() call."""
        if self.collector and hasattr(self.collector, "_last_events"):
            return dict(self.collector._last_events or {})
        return {}
