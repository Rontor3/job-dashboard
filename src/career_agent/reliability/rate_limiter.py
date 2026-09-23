"""Rate limiter — wraps PortalState, enforces daily/hourly caps, adds pace jitter."""
from __future__ import annotations

import os
import random
import time
from urllib.parse import urlparse

from .portal_state import PortalState, _norm

# Pace presets: (min_s, max_s)
_PACE = {
    "fast":   (30,  90),
    "medium": (120, 300),
    "slow":   (480, 900),
}

# stopped_reason → outcome for PortalState
_OUTCOME_MAP = {
    "submitted":              "submitted",
    "reached_submit_dry_run": "dry_run",
    "gate:captcha":           "captcha",
    "gate:hcaptcha":          "captcha",
    "gate:recaptcha":         "captcha",
    "gate:cloudflare_interstitial": "blocked",
    "gate:text_challenge":    "blocked",
}


def map_outcome(stopped_reason: str) -> str:
    if stopped_reason in _OUTCOME_MAP:
        return _OUTCOME_MAP[stopped_reason]
    if "captcha" in stopped_reason.lower():
        return "captcha"
    if "block" in stopped_reason.lower():
        return "blocked"
    return "error"


def domain_key(url: str) -> str:
    netloc = urlparse(url).netloc or url
    return _norm(netloc)


class RateLimiter:
    def __init__(
        self,
        pace: str = "medium",
        domain_day_cap: int | None = None,
        hour_cap: int | None = None,
        state_path=None,
    ):
        self._pace = _PACE.get(pace, _PACE["medium"])
        self._domain_cap = domain_day_cap or int(os.getenv("RATE_LIMIT_DOMAIN_DAY", "5"))
        self._hour_cap   = hour_cap       or int(os.getenv("RATE_LIMIT_HOUR", "10"))
        self._ps = PortalState(path=state_path)
        # In-memory hourly counter — (hour_bucket, count)
        self._hour_bucket: int = self._bucket()
        self._hour_count:  int = 0

    # ------------------------------------------------------------------
    @staticmethod
    def _bucket() -> int:
        return int(time.time() // 3600)

    def _hourly_count(self) -> int:
        b = self._bucket()
        if b != self._hour_bucket:
            self._hour_bucket = b
            self._hour_count = 0
        return self._hour_count

    # ------------------------------------------------------------------
    def domain_key(self, url: str) -> str:
        return domain_key(url)

    def check(self, domain: str) -> str:
        """Returns 'ok', 'defer', or 'cooldown_until:<iso_ts>'."""
        if self._ps.is_cooling(domain):
            ts = self._ps.cooldown_until_ts(domain)
            return f"cooldown_until:{ts}"
        entry = self._ps.get(domain)
        if entry["apps_today"] >= self._domain_cap:
            return "defer"
        if self._hourly_count() >= self._hour_cap:
            return "defer"
        return "ok"

    def record(self, domain: str, outcome: str) -> None:
        self._ps.record_outcome(domain, outcome)
        if outcome in ("submitted", "dry_run"):
            self._hourly_count()   # refresh bucket check
            self._hour_count += 1

    def wait_pace(self, domain: str | None = None) -> None:
        lo, hi = self._pace
        sleep_s = random.uniform(lo, hi)
        print(f"[rate-limiter] pacing {sleep_s:.0f}s before next run", flush=True)
        time.sleep(sleep_s)
