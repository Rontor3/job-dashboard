"""Map a whole screen from the CandidateProfile; collect fields that need the
human. Attestations are never auto-valued; standard questions answered
deterministically; option fields coerced to a real option or escalated."""
from __future__ import annotations

import re

from ..browser.form_model import Field
from ..orchestrator.mapper import FillDecision, _action_for_kind as _action
from ..orchestrator.profile_resolver import resolve
from ..orchestrator import standard_answers

_SELECT_KINDS = {"select", "radio_group"}
_STD_PURPOSES = {"visa_sponsorship", "prior_contact", "work_authorization"}
_YES = {"yes", "y", "true"}
_NO = {"no", "n", "false"}


def _normalize(value):
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return "Yes" if value.strip().lower() == "true" else "No"
    return value


def _coerce_option(value, options):
    v = str(value).strip().lower()
    for o in options:
        if o.strip().lower() == v:
            return o
    toks = _YES if v in _YES else (_NO if v in _NO else None)
    if toks:
        for o in options:
            ol = o.strip().lower()
            if any(re.search(r"\b" + t + r"\b", ol) for t in toks):
                return o
    return None


def _place(f, value, source, decisions, needs_human):
    value = _normalize(value)
    if f.kind in _SELECT_KINDS:
        opt = _coerce_option(value, f.options or [])
        if opt is None:
            needs_human.append(f)
            return
        value = opt
    decisions.append(FillDecision(f.ref, f.kind, f.label, value, _action(f.kind), source))


def map_screen(form, profile, resume_pdf=None):
    decisions, needs_human = [], []
    for f in form:
        if f.kind == "button":
            continue
        if f.purpose == "attestation":
            decisions.append(FillDecision(f.ref, f.kind, f.label, None, "attestation", "flag"))
            continue
        if f.purpose == "resume_upload" or f.kind == "file":
            if resume_pdf:
                decisions.append(FillDecision(f.ref, f.kind, f.label, resume_pdf, "upload", "resume"))
            else:
                needs_human.append(f)
            continue
        if f.purpose in _STD_PURPOSES:
            ans = standard_answers.answer(f.purpose, f.label)
            if ans is None:
                needs_human.append(f)
            else:
                _place(f, ans, "standard", decisions, needs_human)
            continue
        value = resolve(f.purpose, profile) if f.purpose else None
        if value is not None:
            _place(f, value, "resume", decisions, needs_human)
        elif f.required or (f.purpose is None and f.kind in ("text", "textarea")):
            needs_human.append(f)
    return decisions, needs_human


def apply_answers(needs_human, answers):
    out = []
    for f in needs_human:
        v = answers.get(f.ref)
        if v is None:
            continue
        out.append(FillDecision(f.ref, f.kind, f.label, v, _action(f.kind), "human"))
    return out
