"""Map a whole screen from the CandidateProfile; collect fields that need the
human. Attestations are never auto-valued; standard questions answered
deterministically; option fields coerced to a real option or escalated."""
from __future__ import annotations

import re
from datetime import date

from ..orchestrator.mapper import FillDecision, _action_for_kind as _action
from ..orchestrator.profile_resolver import resolve, highest_degree_level, row_degree_level
from ..orchestrator import standard_answers

_SELECT_KINDS = {"select", "radio_group"}
# Free-text purposes answered in prose: when the profile has no value they go to
# the judgment drafter (never to a structured purpose like postal_code).
PROSE_PURPOSES = {"motivation", "summary"}
_STD_PURPOSES = {"visa_sponsorship", "prior_contact", "work_authorization",
                  "phone_type", "referral_source", "conflict_of_interest",
                  "file_comment", "prior_employment"}
# Full-word tokens only — single letters ("y"/"n") mis-coerce "N/A"-style
# options (M-1).
_YES = {"yes", "true"}
_NO = {"no", "false"}
# File fields whose label clearly names a non-résumé document -> never attach
# the résumé there (I-3).
_NON_RESUME_FILE = re.compile(
    r"cover letter|portfolio|photo|picture|transcript|certificate|writing sample", re.I)
# A file box that IMPORTS a profile from the résumé (the site parses it and overwrites fields) rather than attaching it
# to the application. Live Oracle at Cummins (2026-10-18): the parse put 'GenAI' in First Name and 'Unnamed Major'
# education rows. Used only when it is the sole résumé input.
_PROFILE_IMPORT = re.compile(
    r"import (your |my )?(profile|information|details|data)|auto-?fill|auto-?populate|pre-?fill|"
    r"parse (your |my )?(resume|cv)|fill(ing)? (your|the) application (quickly|faster|automatically)", re.I)


def _is_profile_import(f) -> bool:
    return bool(_PROFILE_IMPORT.search(" ".join(x for x in (f.label, getattr(f, "description", None),
                                                           getattr(f, "section", None)) if x)))


# An opt-in to receive things (never ticked unless the form requires it), as opposed to consent to apply.
_MARKETING = re.compile(r"newsletter|marketing|promotion|offers?\b|job alerts?|similar (jobs|roles)|notif|"
                        r"\bsms\b|whatsapp|text messages?|updates? (about|on|from)|talent (community|network|pool)|"
                        r"future (job |career )?(opportunities|openings|roles)|company news|contact me about|keep me (informed|updated)|stay up to date|"
                        r"delivered to (your|my) inbox|news,? and articles|the latest .{0,30}\bjobs\b", re.I)


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
    # "5+" is open-ended; a dial code "(+376)" (plus BEFORE the digits) is not.
    if re.search(r"\d\s*\+", s) or any(k in s for k in ("more than", "over", "at least", "or more", "greater")):
        return (nums[0], _INF)
    if any(k in s for k in ("less than", "under", "fewer", "below")):
        return (0, nums[0] - 1)
    if any(k in s for k in ("up to", "or less", "or fewer", "at most")):
        return (0, nums[0])
    if len(nums) >= 2:
        return (min(nums[0], nums[1]), max(nums[0], nums[1]))
    return (nums[0], nums[0])


_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}


def _unit_days(text):
    """Days per unit named in `text` ('60 days' -> 1, '2 Months' -> 30), or None."""
    m = re.search(r"\b(day|week|month|year)s?\b", (text or "").lower())
    return _UNIT_DAYS[m[1]] if m else None


def _in_days(text):
    """(unit_days, lo, hi) of a quantity-with-unit option/value, in days; None if unitless."""
    u = _unit_days(text)
    band = _option_range(text) if u else None
    return (u, band) if u and band else None


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
            # "I am not a protected veteran" / "I do not have a disability" — option
            # text uses "not" not "no"; skip "prefer not to answer" / "decline" options.
            if toks is _NO and re.search(r"\bnot\b", ol) and not re.search(r"\bprefer\b|\bdecline\b", ol):
                return o
    vnums = re.findall(r"\d+(?:\.\d+)?", v)             # 3. numeric range (never for a dial code like +91)
    if len(vnums) == 1 and not v.startswith("+"):
        n = float(vnums[0])
        vu = _unit_days(v)
        if vu and any(_unit_days(o) for o in options):
            # "60 days" against "2 Months" / "15 Days or less": compare in days, never the bare number against a
            # band in another unit. Options without a unit ("Immediate") take no part.
            n *= vu
            bands = [(o, (b[0] * u, b[1] * u)) for o in options if (u := _unit_days(o)) and (b := _option_range(o))]
            if not any(lo <= n <= hi for _, (lo, hi) in bands):
                return None
        else:
            bands = [(o, b) for o in options if (b := _option_range(o))]
        hits = [(o, b) for o, b in bands if b[0] <= n <= b[1]]
        # Neighbouring bands share their edge ('1-3', '3-5'; '3-5', '5+'): read each as [lo, hi), so a value on the
        # edge belongs to the band it STARTS, as years of experience do (3 years in service = '3-5', not '1-3').
        inside = [o for o, b in hits if n < b[1]]
        if hits:
            return (inside or [o for o, _ in hits])[0]
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


_CURRENT_Q = re.compile(r"^current\s*\??\s*\*?$", re.I)          # Employment History row: "Current? *"
_IN_PROGRESS_Q = re.compile(r"^in progress\s*\??\s*\*?$", re.I)  # Education row: "In Progress *"
_EMPLOYMENT_SECTION = re.compile(r"employ|experience|work history", re.I)
_EDUCATION_SECTION = re.compile(r"educat|academic|school|degree", re.I)
_OPEN_END = re.compile(r"^\s*(present|current|now|ongoing|to date|till date|today)\s*$", re.I)
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")


def _ends_open(end: str) -> bool:
    """An entry's end date says it is still running: 'Present', or a year not yet past."""
    if _OPEN_END.match(end or ""):
        return True
    m = _YEAR.search(end or "")
    return bool(m) and int(m.group(1)) >= date.today().year


def _entry_answer(f, profile):
    """'Current?' on an Employment row / 'In Progress' on an Education row, answered from that row's own entry.
    Empty end = still running for a job; for a degree, no end date means nothing says it is ongoing -> No."""
    if f.kind not in _SELECT_KINDS:
        return None
    row = max(f.row, 0)                    # the only entry of its section carries no row number: it is the first
    label = (f.label or "").strip()
    section = f.section or ""
    if _CURRENT_Q.match(label) and _EMPLOYMENT_SECTION.search(section):
        rows, open_ = profile.experiences, lambda e: not (e.end or "").strip() or _ends_open(e.end)
    elif _IN_PROGRESS_Q.match(label) and _EDUCATION_SECTION.search(section):
        rows, open_ = profile.education, lambda e: _ends_open(e.end)
    else:
        return None
    if row >= len(rows):
        return None
    return "Yes" if open_(rows[row]) else "No"


def _is_yes_no(f) -> bool:
    return (f.kind in _SELECT_KINDS and bool(f.options)
            and _coerce_option("Yes", f.options) is not None and _coerce_option("No", f.options) is not None)


def _place(f, value, source, decisions, needs_human):
    value = _normalize(value)
    if f.kind in _SELECT_KINDS:
        if f.options:
            # Options known: coerce to a real option or escalate.
            opt = _coerce_option(value, f.options)
            if opt is None:
                needs_human.append(f)
                return
            value = opt
        # Empty options = lazy-loaded DOM; pass raw value and let filler
        # attempt select_option(label=value) — fails softly if no match.
    decisions.append(FillDecision(f.ref, f.kind, f.label, value, _action(f.kind), source))


_CRED_PURPOSES = ("password", "password_new", "password_confirm")
_HIGHEST_DEGREE = re.compile(r"highest|diploma obtained", re.I)


def _degree_level(f, profile, school_by_row):
    """A degree SELECT wants a level ("Bachelor's Degree"), not the profile's degree as written ("B.Tech").
    'Highest Degree' = the top level in the profile; a repeated row's Degree = the level of the entry its School names."""
    if f.row < 0 or _HIGHEST_DEGREE.search(f.label or ""):
        return highest_degree_level(profile)
    return row_degree_level(profile, f.row, school_by_row.get((f.section, f.row)))


def map_screen(form, profile, resume_pdf=None):
    decisions, needs_human = [], []
    # The School text box of each education row, as the page holds it (the résumé import fills it).
    school_by_row = {(f.section, f.row): f.value for f in form if f.purpose == "school" and f.row >= 0 and f.value}
    for f in form:
        if f.kind == "button":
            continue
        if f.purpose in _CRED_PURPOSES:
            # Auth-wall credential fields — credential_provider handles these.
            # Never fill or escalate; pretend they don't exist.
            continue
        if f.kind == "checkbox_group":
            # One question for the whole cluster, or nothing: optional boxes are left blank
            # saintly ("How did you hear about us?": nine boxes came in as nine 'questions',
            # Twilio live 2026-10-19); a required group is answered once, coerced to its
            # options like any select.
            if not f.required:
                continue
            ans = standard_answers.answer(f.purpose, f.label) if f.purpose in _STD_PURPOSES else None
            if ans is not None:
                _place(f, ans, "standard", decisions, needs_human)
                continue
            needs_human.append(f)
            continue
        if _is_yes_no(f) and _MARKETING.search(f"{f.label} {getattr(f, 'description', '')}"):
            # Marketing opt-in (SMS / future-opportunity emails), required or not: privacy-preserving default is No.
            _place(f, "No", "policy", decisions, needs_human)
            continue
        if f.purpose == "attestation":
            # Tick privacy / terms / certify consent in the DRAFT, marked required or not (the user's standing yes,
            # 2026-10-13: an unmarked privacy box kept Tibil's Apply greyed out) — a tick on an unsubmitted form binds
            # nothing; the human-approved SUBMIT is the consent point. Marketing opt-ins stay unticked.
            if f.kind in _SELECT_KINDS and f.options:
                # A declaration offered as True/False or Yes/No: only a required one is answered — an optional
                # "terms" radio is as likely a question ("employment terms: full/part time") as a declaration.
                if not f.required:
                    decisions.append(FillDecision(f.ref, f.kind, f.label, None, "attestation", "flag"))
                    continue
                opt = _coerce_option("Yes", f.options)
                if opt is None:
                    needs_human.append(f)
                else:
                    decisions.append(FillDecision(f.ref, f.kind, f.label, opt, _action(f.kind), "attestation"))
                continue
            if f.required or not _MARKETING.search(f"{f.label} {getattr(f, 'description', '')}"):
                decisions.append(FillDecision(f.ref, f.kind, f.label, True, "check", "attestation"))
            else:
                decisions.append(FillDecision(f.ref, f.kind, f.label, None, "attestation", "flag"))
            continue
        if f.purpose == "resume_upload" or f.kind == "file":
            is_resume = f.purpose == "resume_upload" or not _NON_RESUME_FILE.search(f.label or "")
            if is_resume and _is_profile_import(f) and any(
                    g is not f and g.kind == "file" and not _is_profile_import(g)
                    and not _NON_RESUME_FILE.search(g.label or "") for g in form):
                print(f"[fill] résumé not sent to the profile-import box {f.label[:50]!r} (a document slot exists)",
                      flush=True)
                continue                                  # the document slot gets it; the parser would overwrite fields
            if not is_resume or not resume_pdf:
                needs_human.append(f)
                continue
            if f.kind in ("radio_group", "radio"):
                # Upload-selection radio (Taleo page 1): each option is its own radio group.
                # Click only the radio whose option text mentions "upload" or "file".
                # Skip LinkedIn and "Skip" radios.
                upload_opt = next(
                    (o for o in (f.options or []) if re.search(r"\bupload\b|\bfile\b", o, re.I)),
                    None,
                )
                if upload_opt:
                    decisions.append(FillDecision(f.ref, f.kind, f.label, upload_opt, "check_group", "resume"))
                # else: LinkedIn or Skip radio — leave it, the upload radio handles it
            else:
                decisions.append(FillDecision(f.ref, f.kind, f.label, resume_pdf, "upload", "resume"))
            continue
        if f.purpose in _STD_PURPOSES:
            ans = standard_answers.answer(f.purpose, f.label)
            if ans is None:
                needs_human.append(f)
            else:
                _place(f, ans, "standard", decisions, needs_human)
            continue
        entry = _entry_answer(f, profile)
        if entry is not None:
            _place(f, entry, "profile", decisions, needs_human)
            continue
        # a search-as-you-type degree box loads its options only when typed into (Koch Avature: 'Bachelor's Degree'
        # matches, 'B.Tech' finds nothing): it wants the level too
        if f.purpose == "degree" and ((f.kind in _SELECT_KINDS and f.options) or f.kind == "combobox"):
            level = _degree_level(f, profile, school_by_row)
            if level is None:
                needs_human.append(f)
            else:
                _place(f, level, "profile", decisions, needs_human)
            continue
        value = resolve(f.purpose, profile) if f.purpose else None
        if value is not None:
            _place(f, value, "resume", decisions, needs_human)
        elif f.required or (f.kind == "textarea" or (f.kind == "text" and f.purpose in PROSE_PURPOSES)):
            # an OPTIONAL single-line field with no answer stays blank — escalating it parks the run on a human
            needs_human.append(f)
    # Invariant: a required field leaves the screen as a decision or an escalation, never silently. The only
    # deliberate skips above are credential-owned passwords and a résumé-import box (the document slot takes the file).
    seen = {d.ref for d in decisions} | {f.ref for f in needs_human}
    for f in form:
        if (f.required and f.kind != "button" and f.ref not in seen and f.purpose not in _CRED_PURPOSES
                and not (f.kind == "file" and _is_profile_import(f))):
            print(f"[fill] required field {f.label[:50]!r} had no decision — escalated", flush=True)
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
