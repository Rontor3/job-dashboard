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


class CliCollector:
    """Collects answers for fields the profile couldn't fill, on stdin. The
    HumanLoop `collector` contract: fields -> {ref: value}. Telegram-collect
    drops in behind the same shape later. A blank answer leaves the field for
    the next screen review rather than filling it with an empty string."""
    def __call__(self, fields) -> dict:
        out: dict = {}
        for f in fields:
            answer = input(f"Value for {f.label or f.ref!r}: ").strip()
            if answer:
                out[f.ref] = answer
        return out
