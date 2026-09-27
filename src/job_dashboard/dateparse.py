"""Normalize the many `posted_date` shapes our sources hand back into one ISO8601
UTC string, so date comparisons/sorts (the 30-day window, "date" sort) work the
same across every source. Never raises — an unrecognized shape passes through
unchanged rather than being dropped, so we never silently lose a job's date.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_RELATIVE = re.compile(
    r"^\s*(today|yesterday|(\d+)\s*(hour|hr|day|week|month)s?\s*ago)\s*$", re.IGNORECASE
)
_EPOCH = re.compile(r"^\d{10,13}$")


def normalize_posted_date(raw, *, now=None) -> str | None:
    """`raw` -> ISO8601 UTC string, or None if empty. Unrecognized non-empty
    strings are returned as-is (unchanged) rather than dropped."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    now = now or datetime.now(timezone.utc)

    if _EPOCH.match(s):
        # 10 digits = seconds, 13 = milliseconds.
        seconds = int(s) / 1000 if len(s) == 13 else int(s)
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()

    m = _RELATIVE.match(s)
    if m:
        if m.group(1).lower() == "today":
            return now.isoformat()
        if m.group(1).lower() == "yesterday":
            return (now - timedelta(days=1)).isoformat()
        n, unit = int(m.group(2)), m.group(3).lower()
        delta = {"hour": timedelta(hours=n), "hr": timedelta(hours=n), "day": timedelta(days=n),
                 "week": timedelta(weeks=n), "month": timedelta(days=30 * n)}[unit]
        return (now - delta).isoformat()

    try:
        # Accepts date-only ("2026-09-27"), datetime with/without offset, "Z" suffix.
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.isoformat()
    except ValueError:
        return s  # unrecognized shape: keep the original rather than lose the data
