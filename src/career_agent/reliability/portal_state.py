"""Per-domain portal state — tracks captcha escalations, daily app counts, cooldowns.

Storage: ~/.career_agent/portal_state.json (one entry per normalised domain key).
"""
from __future__ import annotations

import json
import pathlib
import time
from datetime import date, datetime, timezone

_DEFAULT_PATH = pathlib.Path.home() / ".career_agent" / "portal_state.json"

# Prefixes stripped when normalising domain keys so jobs.greenhouse.io == greenhouse.io
_STRIP_PREFIXES = ("jobs.", "careers.", "apply.", "boards.", "www.")


def _norm(domain: str) -> str:
    d = domain.lower().strip()
    for p in _STRIP_PREFIXES:
        if d.startswith(p):
            d = d[len(p):]
    return d


def _blank(today: str) -> dict:
    return {
        "apps_today": 0,
        "apps_today_date": today,
        "apps_total": 0,
        "escalation_count": 0,
        "cooldown_until": None,
        "cooldown_base_s": 3600,
        "last_run": None,
    }


class PortalState:
    def __init__(self, path: pathlib.Path | None = None):
        self._path = path or _DEFAULT_PATH

    # ------------------------------------------------------------------
    def _read(self) -> dict:
        try:
            return json.loads(self._path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2))

    # ------------------------------------------------------------------
    def get(self, domain: str) -> dict:
        key = _norm(domain)
        today = date.today().isoformat()
        data = self._read()
        entry = data.get(key, _blank(today))
        # Reset daily counter if date rolled over
        if entry["apps_today_date"] != today:
            entry["apps_today"] = 0
            entry["apps_today_date"] = today
        return entry

    def record_outcome(self, domain: str, outcome: str) -> None:
        """outcome ∈ {submitted, dry_run, captcha, blocked, error}"""
        key = _norm(domain)
        data = self._read()
        today = date.today().isoformat()
        entry = data.get(key, _blank(today))
        if entry["apps_today_date"] != today:
            entry["apps_today"] = 0
            entry["apps_today_date"] = today

        entry["last_run"] = datetime.now(timezone.utc).isoformat()

        if outcome in ("submitted", "dry_run"):
            entry["apps_today"] += 1
            entry["apps_total"] += 1
            entry["escalation_count"] = 0
            entry["cooldown_until"] = None
            entry["cooldown_base_s"] = 3600
        elif outcome in ("captcha", "blocked"):
            entry["escalation_count"] += 1
            if outcome == "blocked":
                entry["cooldown_base_s"] = min(entry["cooldown_base_s"] * 2, 86400)
            cooldown_s = entry["cooldown_base_s"] * (2 ** (entry["escalation_count"] - 1))
            entry["cooldown_until"] = (
                datetime.fromtimestamp(time.time() + cooldown_s, tz=timezone.utc).isoformat()
            )
        # outcome == "error" → no counter change

        data[key] = entry
        self._write(data)

    def is_cooling(self, domain: str) -> bool:
        entry = self.get(domain)
        until = entry.get("cooldown_until")
        if not until:
            return False
        return time.time() < datetime.fromisoformat(until).timestamp()

    def cooldown_until_ts(self, domain: str) -> str | None:
        entry = self.get(domain)
        return entry.get("cooldown_until")

    def reset_cooldown(self, domain: str) -> None:
        key = _norm(domain)
        data = self._read()
        if key in data:
            data[key]["cooldown_until"] = None
            data[key]["escalation_count"] = 0
            self._write(data)
