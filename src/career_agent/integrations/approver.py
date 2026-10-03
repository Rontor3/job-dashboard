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


class NullCollector:
    """Auto-skips all human fields — used for unattended dry-runs/screenshots."""
    def __call__(self, fields) -> dict:
        for f in fields:
            print(f"[skip] human field: {f.label or f.ref!r}", flush=True)
        return {}


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



class PresetCollector:
    """Answers the human already gave (e.g. in chat), matched by label, so a run
    does not wait on Telegram for them. `answers` maps a phrase to a value; a field
    is answered when its normalized label contains the normalized phrase. Fields
    with no preset go to `inner` (Telegram/CLI) unchanged."""

    def __init__(self, answers: dict, inner=None):
        import re
        self._norm = lambda s: re.sub(r"\W+", " ", str(s or "").lower()).strip()
        self.answers = {self._norm(k): str(v) for k, v in (answers or {}).items() if self._norm(k)}
        self.inner = inner
        self._last_events: dict = {}

    def __getattr__(self, name):          # jd_text etc. belong to the inner collector
        if name.startswith("__") or self.inner is None:
            raise AttributeError(name)
        return getattr(self.inner, name)

    def __call__(self, fields) -> dict:
        out, rest = {}, []
        self._last_events = {}
        for f in fields:
            label = self._norm(f.label)
            hit = next((v for k, v in self.answers.items() if k in label), None)
            if hit is None:
                rest.append(f)
            else:
                out[f.ref] = hit
                self._last_events[f.ref] = "approve"
                print(f"[preset] {f.label[:60]!r} -> {hit!r}", flush=True)
        if rest and self.inner is not None:
            out.update(dict(self.inner(rest) or {}))
            self._last_events.update(getattr(self.inner, "_last_events", {}) or {})
        return out
