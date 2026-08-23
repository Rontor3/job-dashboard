"""Human approval interface. CLI now; Telegram later drops in behind the
same `request(card) -> bool` contract."""
from __future__ import annotations

from typing import Protocol


class Approver(Protocol):
    def request(self, card: str) -> bool: ...


class CliApprover:
    def request(self, card: str) -> bool:
        print(card)
        answer = input("\nSubmit this application? [y/N] ").strip().lower()
        return answer in ("y", "yes")


class AutoDenyApprover:
    """Never approves — safe default for unattended / dry-run."""
    def request(self, card: str) -> bool:
        return False
