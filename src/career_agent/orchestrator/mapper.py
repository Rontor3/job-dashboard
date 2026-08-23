"""Field mapper: Form Model + profile -> per-field fill decisions.

Pure. Direct profile fields fill automatically; attestations are flagged
never valued; anything unknown or unbacked becomes a human-review item."""
from __future__ import annotations

from dataclasses import dataclass

from ..browser.form_model import Field

# purpose -> application_profile key (same-name)
_PROFILE_KEYS = {
    "full_name", "email", "phone", "location", "linkedin_url", "github_url",
    "portfolio_url", "work_authorization", "years_experience",
    "notice_period", "salary_expectation",
}


@dataclass(frozen=True)
class FillDecision:
    ref: str
    kind: str
    label: str
    value: object
    action: str
    source: str


def _action_for_kind(kind: str) -> str:
    if kind == "select":
        return "select"
    if kind == "radio_group":
        return "check_group"
    return "fill"


def map_fields(form: list[Field], profile: dict, resume_path: str | None) -> list[FillDecision]:
    out: list[FillDecision] = []
    for f in form:
        if f.purpose == "attestation":
            out.append(FillDecision(f.ref, f.kind, f.label, None, "attestation", "flag"))
            continue
        if f.purpose == "resume_upload":
            out.append(FillDecision(f.ref, f.kind, f.label, resume_path, "upload", "profile"))
            continue
        if f.purpose in _PROFILE_KEYS and profile.get(f.purpose):
            out.append(FillDecision(
                f.ref, f.kind, f.label, profile[f.purpose],
                _action_for_kind(f.kind), "profile"))
            continue
        out.append(FillDecision(f.ref, f.kind, f.label, None, "review", "none"))
    return out
