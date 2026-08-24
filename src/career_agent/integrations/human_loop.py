"""Facade the run loop talks to: approvals and remote-solve. Keeps the run
loop ignorant of Telegram/CDP details, and degrades safely when remote solve
is not configured."""
from __future__ import annotations


class HumanLoop:
    def __init__(self, approver, remote_solve_factory=None, deadline_s: int = 900):
        self.approver = approver
        self.remote_solve_factory = remote_solve_factory
        self.deadline_s = deadline_s

    def approve(self, card: str) -> bool:
        return self.approver.request(card)

    def remote_solve(self, page, gate: str, on_link) -> bool:
        if self.remote_solve_factory is None:
            return False  # caller degrades to Phase-1 stop-and-report
        # Any failure to stand up the live view (CDP error, port bind, a
        # public-host build_url refusal) must degrade to stop-and-report, never
        # crash the run — the gate stays escalated and nothing is submitted.
        session = None
        try:
            session = self.remote_solve_factory(page)
            on_link(session.start())
            return bool(session.wait_until_cleared(self.deadline_s))
        except Exception:
            return False
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
