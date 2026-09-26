"""Shared types for browser (CDP) job sources."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable


class Blocked(Exception):
    """The site challenged or blocked us (login wall, captcha, 403/429...). Never retried."""


class CapReached(Exception):
    """Per-run page-load cap hit. Not an error: known jobs are skipped next time, so the
    next run continues where this one stopped."""


@dataclass
class AdapterContext:
    mode: str                                  # "backfill" | "incremental"
    known: Callable[[str, str], bool]          # (external_id, canonical_url) -> already in the DB
    terms: list
    max_pages: int
    stop_after_known: int
    hours: int = 48                            # incremental look-back window (a linkedin.TPR key)
    stats: dict = field(default_factory=lambda: {"skipped_known": 0, "pages": 0})


@dataclass
class SiteResult:
    site: str
    mode: str = ""
    new: int = 0
    skipped_known: int = 0
    pages: int = 0
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)
