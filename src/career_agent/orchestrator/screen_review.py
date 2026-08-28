"""Map a whole screen from the CandidateProfile; collect fields that need the
human. Attestations are never auto-valued; novel required questions escalate."""
from __future__ import annotations

from ..browser.form_model import Field
from ..orchestrator.mapper import FillDecision, _action_for_kind as _action
from ..orchestrator.profile_resolver import resolve

_SELECT_KINDS = {"select", "radio_group"}


def map_screen(form, profile):
    decisions, needs_human = [], []
    for f in form:
        if f.kind == "button":
            continue  # nav / submit controls: handled by the advance logic
        if f.purpose == "attestation":
            decisions.append(FillDecision(f.ref, f.kind, f.label, None, "attestation", "flag"))
            continue
        value = resolve(f.purpose, profile) if f.purpose else None
        if value is not None:
            if f.kind in _SELECT_KINDS and value not in (f.options or []):
                needs_human.append(f)          # can't safely pick an option
                continue
            decisions.append(FillDecision(f.ref, f.kind, f.label, value, _action(f.kind), "resume"))
        elif f.required or (f.purpose is None and f.kind in ("text", "textarea")):
            needs_human.append(f)              # required-unknown or novel question
    return decisions, needs_human


def apply_answers(needs_human, answers):
    out = []
    for f in needs_human:
        v = answers.get(f.ref)
        if v is None:
            continue
        out.append(FillDecision(f.ref, f.kind, f.label, v, _action(f.kind), "human"))
    return out
