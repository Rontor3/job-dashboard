"""Pure, side-effect-free eligibility assessment (no DB/network).

Down-ranks (never drops) a job when the candidate clearly can't clear a hard
bar: a large required-experience gap, or a stated region the candidate isn't in.
Missing info -> no penalty. NEVER raises.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_YEARS_RE = re.compile(r"(\d+)\s*\+?\s*years?", re.IGNORECASE)
# "Hires remotely in: <list>" / "accepts applications from <list>"
_HIRES_IN_RE = re.compile(
    r"(?:hires remotely in|accepts? applications? from|open to candidates in)\s*[:\-]?\s*([^.\n]+)",
    re.IGNORECASE,
)
# A listed region containing any of these means "all regions" -- it INCLUDES the
# candidate's region, so it must NOT trip the region gate ("Remote: Everywhere").
_UNIVERSAL_REGIONS = ("everywhere", "worldwide", "world wide", "global",
                      "anywhere", "any location", "all locations")


@dataclass
class EligibilityResult:
    demote: bool = False
    flags: list[str] = field(default_factory=list)


def parse_required_years(text) -> float | None:
    if not isinstance(text, str):
        return None
    nums = [int(m) for m in _YEARS_RE.findall(text)]
    return float(max(nums)) if nums else None


def candidate_years_from_profile(profile_text, default: float = 2.0) -> float:
    y = parse_required_years(profile_text if isinstance(profile_text, str) else "")
    return y if y is not None else float(default)


def assess_eligibility(description, candidate_years, candidate_region: str = "India",
                       gap_threshold: float = 3.0) -> EligibilityResult:
    try:
        text = description if isinstance(description, str) else ""
        cyears = float(candidate_years) if candidate_years is not None else 0.0
        flags: list[str] = []
        demote = False

        req = parse_required_years(text)
        if req is not None and (req - cyears) > gap_threshold:
            demote = True
            flags.append(f"requires {req:.0f}y experience, profile has ~{cyears:.0f}y")

        region = (candidate_region or "").strip().lower()
        for m in _HIRES_IN_RE.finditer(text):
            listed = m.group(1).lower()
            universal = any(u in listed for u in _UNIVERSAL_REGIONS)
            if region and not universal and region not in listed:
                demote = True
                flags.append(f"may not accept applicants from {candidate_region}")
                break

        return EligibilityResult(demote=demote, flags=flags)
    except Exception:
        return EligibilityResult(demote=False, flags=[])
