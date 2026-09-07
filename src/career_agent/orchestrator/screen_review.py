"""Map a whole screen from the CandidateProfile; collect fields that need the
human. Attestations are never auto-valued; standard questions answered
deterministically; option fields coerced to a real option or escalated."""
from __future__ import annotations

import re

from ..orchestrator.mapper import FillDecision, _action_for_kind as _action
from ..orchestrator.profile_resolver import resolve
from ..orchestrator import standard_answers

_SELECT_KINDS = {"select", "radio_group"}
_STD_PURPOSES = {"visa_sponsorship", "prior_contact", "work_authorization"}
# Full-word tokens only — single letters ("y"/"n") mis-coerce "N/A"-style
# options (M-1).
_YES = {"yes", "true"}
_NO = {"no", "false"}
# File fields whose label clearly names a non-résumé document -> never attach
# the résumé there (I-3).
_NON_RESUME_FILE = re.compile(
    r"cover letter|portfolio|photo|picture|transcript|certificate|writing sample", re.I)


def _normalize(value):
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return "Yes" if value.strip().lower() == "true" else "No"
    return value


_INF = float("inf")


def _option_range(opt):
    """Parse an option label into a numeric [lo, hi] band, or None. Handles the
    common experience/count shapes: '3-5', '3 to 5', '5+', 'More than 5',
    'Less than 2', 'Up to 2', '10 years'."""
    s = opt.strip().lower()
    nums = [int(n) for n in re.findall(r"\d+", s)]
    if not nums:
        return None
    if any(k in s for k in ("+", "more than", "over", "at least", "or more", "greater")):
        return (nums[0], _INF)
    if any(k in s for k in ("less than", "under", "fewer", "below")):
        return (0, nums[0] - 1)
    if any(k in s for k in ("up to", "or less", "or fewer", "at most")):
        return (0, nums[0])
    if len(nums) >= 2:
        return (min(nums[0], nums[1]), max(nums[0], nums[1]))
    return (nums[0], nums[0])


def _coerce_option(value, options):
    """Map a profile value onto one of a field's real options. Tries, in order:
    exact, yes/no word, numeric-range containment (e.g. 3 -> '3-5 years'), then
    whole-word containment. Returns the matched option, or None to escalate."""
    v = str(value).strip().lower()
    if not v:
        return None
    for o in options:                                   # 1. exact
        if o.strip().lower() == v:
            return o
    toks = _YES if v in _YES else (_NO if v in _NO else None)   # 2. yes / no
    if toks:
        for o in options:
            ol = o.strip().lower()
            if any(re.search(r"\b" + t + r"\b", ol) for t in toks):
                return o
    vnums = re.findall(r"\d+", v)                        # 3. numeric range
    if len(vnums) == 1:
        n = int(vnums[0])
        for o in options:
            band = _option_range(o)
            if band and band[0] <= n <= band[1]:
                return o
    vt = [t for t in re.findall(r"[a-z0-9]+", v) if len(t) > 1]   # 4. word containment
    if vt:
        vset = set(vt)
        for o in options:                          # 4a. every value word is in the option
            ol = o.strip().lower()
            if all(re.search(r"\b" + re.escape(t) + r"\b", ol) for t in vt):
                return o
        # 4b. every option word is in the value ("Mumbai, India" -> option "Mumbai");
        # prefer the longest such option so a city beats a bare country.
        subset = []
        for o in options:
            ot = [t for t in re.findall(r"[a-z0-9]+", o.lower()) if len(t) > 1]
            if ot and all(t in vset for t in ot):
                subset.append(o)
        if subset:
            return max(subset, key=len)
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
            # Tick REQUIRED attestations (T&C / e-signature) in the DRAFT — a tick
            # on an unsubmitted form binds nothing; the human-approved SUBMIT is
            # the consent point. Optional attestations (e.g. marketing opt-in) are
            # left unticked.
            if f.required:
                decisions.append(FillDecision(f.ref, f.kind, f.label, True, "check", "attestation"))
            else:
                decisions.append(FillDecision(f.ref, f.kind, f.label, None, "attestation", "flag"))
            continue
        if f.purpose == "resume_upload" or f.kind == "file":
            is_resume = f.purpose == "resume_upload" or not _NON_RESUME_FILE.search(f.label or "")
            if is_resume and resume_pdf:
                decisions.append(FillDecision(f.ref, f.kind, f.label, resume_pdf, "upload", "resume"))
            else:
                needs_human.append(f)   # non-résumé file, or no résumé available
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
        elif f.required or (f.purpose is None and f.kind == "text"):
            needs_human.append(f)     # optional catch-all textareas -> left blank
    return decisions, needs_human


def apply_answers(needs_human, answers):
    out = []
    for f in needs_human:
        v = answers.get(f.ref)
        if v is None:
            continue
        out.append(FillDecision(f.ref, f.kind, f.label, v, _action(f.kind), "human"))
    return out
