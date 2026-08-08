"""Compute a job posting's age in days from its (source-varying, messy)
``posted_date``, falling back to ``fetched_at``.

Sources store wildly different formats: ISO dates ("2026-07-17"), ISO datetimes
("2026-07-16T10:10:51"), relative strings ("2 Days Ago"), unix epochs
("1784014893"), or nothing at all. This normalizes them to an age in days so the
feed can hide stale postings and sort by recency. Pure; never raises — returns
``None`` when the age genuinely can't be determined.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_REL = re.compile(r"(\d+)\s*(min|hour|hr|day|week|month|year|yr)s?\s*ago", re.I)
_REL_UNIT_DAYS = {"min": 1 / 1440, "hour": 1 / 24, "hr": 1 / 24, "day": 1,
                  "week": 7, "month": 30, "year": 365, "yr": 365}


def _parse_dt(s):
    """Parse an absolute timestamp: unix epoch seconds, or ISO date/datetime."""
    if not s:
        return None
    s = str(s).strip()
    if s.isdigit() and len(s) >= 9:  # unix epoch seconds
        try:
            return datetime.fromtimestamp(int(s), tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def job_age_days(posted_date, fetched_at, now=None):
    """Age of the posting in days, or ``None`` if it can't be determined.

    Precedence: a relative ``posted_date`` ("2 Days Ago") anchored on
    ``fetched_at`` (when we scraped it) → an absolute ``posted_date`` → the
    ``fetched_at`` fallback.
    """
    try:
        now = now or datetime.now(timezone.utc)

        if posted_date:
            m = _REL.search(str(posted_date))
            if m:
                span = int(m.group(1)) * _REL_UNIT_DAYS[m.group(2).lower()]
                anchor = _parse_dt(fetched_at) or now
                posted = anchor - timedelta(days=span)
                return max(0.0, (now - posted).total_seconds() / 86400)

        dt = _parse_dt(posted_date) or _parse_dt(fetched_at)
        if dt is None:
            return None
        return max(0.0, (now - dt).total_seconds() / 86400)
    except Exception:  # noqa: BLE001 — never raise; unknown age
        return None
