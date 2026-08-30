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


_OPTION_KINDS = {"select", "radio_group"}


def _action_for_kind(kind: str) -> str:
    if kind == "select":
        return "select"
    if kind == "radio_group":
        return "check_group"
    if kind == "combobox":
        return "combobox"           # open the fake dropdown + click a live option
    return "fill"


def _review(f: Field) -> FillDecision:
    return FillDecision(f.ref, f.kind, f.label, None, "review", "none")


def map_fields(form: list[Field], profile: dict, resume_path: str | None) -> list[FillDecision]:
    out: list[FillDecision] = []
    for f in form:
        if f.kind == "button":
            continue  # nav / submit controls aren't fillable — not a card item
        if f.purpose == "attestation":
            out.append(FillDecision(f.ref, f.kind, f.label, None, "attestation", "flag"))
            continue
        if f.purpose == "resume_upload":
            if resume_path:
                out.append(FillDecision(f.ref, f.kind, f.label, resume_path, "upload", "profile"))
            else:
                out.append(_review(f))
            continue
        if f.purpose in _PROFILE_KEYS and profile.get(f.purpose):
            value = profile[f.purpose]
            # Option-backed fields (select / radio group) only auto-fill when
            # the profile value is literally one of the options. Deciding that
            # e.g. "US Citizen" == "Yes" is judgment for the LLM tier (later
            # phase), so an unmatched value becomes a human-review item rather
            # than a blind click that would hang on a missing option.
            if f.kind in _OPTION_KINDS and value not in (f.options or []):
                out.append(_review(f))
                continue
            out.append(FillDecision(
                f.ref, f.kind, f.label, value, _action_for_kind(f.kind), "profile"))
            continue
        out.append(_review(f))
    return out
