"""Deterministic answer rules and text-shape checks for the question bank.

A rule turns an entry into a value for THIS job; it returns None when it can't
decide (unknown job city, entry unanswered) — None always means "flag it",
never a guess. Rules are plain Python so no answer logic lives in the DB."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

_NONE_WORDS = {"", "none", "n/a", "na", "-"}


@dataclass
class RuleCtx:
    question: str                      # the page's question, escape instruction removed
    answer: str | None                 # this entry's own stored answer (a list, a table…)
    escape: str | None                 # word the page asked to type ("relocating"), if any
    job: dict                          # jobs row for this run: company, location
    bank: Callable[[str], str | None]  # entry id -> resolved answer of another entry
    options: list = field(default_factory=list)    # the page field's options (pick-one questions)
    synonyms: dict = field(default_factory=dict)   # entry synonyms; for preference: {alternative: [keywords]}


def _items(s) -> list[str]:
    return [x.strip().lower() for x in re.split(r"[,;\n]", s or "")
            if x.strip().lower() not in _NONE_WORDS]


def local_or_escape(c: RuleCtx):
    """Job in a local city (or remote) -> home address; elsewhere -> the page's
    escape word ("relocating"). Unknown job location -> None."""
    loc = (c.job.get("location") or "").lower()
    if not loc:
        return None
    if "remote" in loc or any(city in loc for city in _items(c.bank("local_cities"))):
        return c.bank("home_address")
    return c.escape


def empty_or_escape(c: RuleCtx):
    """Your value, or the page's escape word ("N/A") when you have none."""
    if c.answer is None:
        return None
    if c.answer.strip().lower() in _NONE_WORDS:
        return c.escape
    return c.answer


def country_is_home(c: RuleCtx):
    """Yes if the question names India only, No if it names another country,
    None if neither/both (same logic as standard_answers work_authorization)."""
    from ..orchestrator.standard_answers import answer
    return answer("work_authorization", c.question)


def company_in_list(c: RuleCtx):
    """Entry answer = companies where the answer is Yes (or 'none')."""
    company = (c.job.get("company") or "").strip().lower()
    if not company or c.answer is None:
        return None
    return "Yes" if any(re.search(rf"\b{re.escape(x)}\b", company) for x in _items(c.answer)) else "No"


def years_in_skill(c: RuleCtx):
    """Entry answer = 'python=3, sql=3, default=2'; first skill named wins."""
    table = {}
    for part in re.split(r"[,;\n]", c.answer or ""):
        if "=" in part:
            k, v = part.split("=", 1)
            table[k.strip().lower()] = v.strip()
    q = (c.question or "").lower()
    best = None
    for skill, yrs in table.items():
        if skill == "default":
            continue
        m = re.search(rf"\b{re.escape(skill)}\b", q)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), yrs)
    return best[1] if best else table.get("default")


_YESNO = {"yes", "no", "true", "false"}


def _pref(answer):
    """'A > B > C; not: X, Y' -> (['A','B','C'], ['X','Y'])."""
    head, _, tail = (answer or "").partition(";")
    order = [x.strip() for x in head.split(">") if x.strip()]
    nope = []
    if tail.strip().lower().startswith("not"):
        nope = [x.strip() for x in tail.split(":", 1)[-1].split(",") if x.strip()]
    return order, nope


def _named(text, synonyms, alts):
    """Alternatives whose keywords appear (whole word, any case) in text."""
    t = (text or "").lower()
    return [a for a in alts if any(re.search(rf"(?<!\w){re.escape(k.lower())}(?!\w)", t)
                                   for k in (synonyms.get(a) or [a]))]


def preference(c: RuleCtx):
    """Ordered acceptable alternatives -> the page's pick-one option, or Yes/No for a yes/no wording."""
    order, nope = _pref(c.answer)
    if not order:
        return None
    alts = order + nope
    opts = [o for o in c.options if o.strip().lower() not in _YESNO]
    if opts:
        by_alt = {}
        for o in opts:
            hit = _named(o, c.synonyms, alts)
            if len(hit) == 1:
                by_alt.setdefault(hit[0], o)
        return next((by_alt[a] for a in order if a in by_alt), None)
    named = _named(c.question, c.synonyms, alts)
    if not named:
        return None if c.options else order[0]
    ok = [a in order for a in named]
    return "Yes" if all(ok) else "No" if not any(ok) else None


RULES = {f.__name__: f for f in (local_or_escape, empty_or_escape, country_is_home,
                                 company_in_list, years_in_skill, preference)}
NO_INPUT_RULES = {"local_or_escape", "country_is_home"}
RULE_HELP = {
    "local_or_escape": "Worked out per job: your home address if the job is in one of your local cities or remote, otherwise the word the form asks for (e.g. \"relocating\").",
    "empty_or_escape": "Your value, or 'none' if you don't have one (the form's N/A word is used then).",
    "country_is_home": "Worked out per question: Yes for India, No for any other country named.",
    "company_in_list": "Companies where the answer is Yes, comma-separated — or 'none'.",
    "years_in_skill": "skill=years pairs, e.g. python=3, sql=3, default=2",
    "preference": "Best first, separated by >, e.g. Remote > Hybrid > Onsite. Add '; not: X, Y' for options you refuse. Pick-one questions get your highest-ranked offered option; yes/no questions get Yes if the option asked about is on your list, No if refused.",
}

# ── shapes ──────────────────────────────────────────────────────────────────
SHAPES = {
    "email": lambda v: bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.\w+", v)),
    "phone": lambda v: len(re.sub(r"\D", "", v)) >= 10,
    "url": lambda v: v.startswith(("http://", "https://")),
    "number": lambda v: bool(re.fullmatch(r"\d+(\.\d+)?", v)),
    "postcode": lambda v: bool(re.fullmatch(r"\d{6}", v)),
    "date": lambda v: bool(re.search(r"\d", v)),
    "address": lambda v: len(v.split()) >= 3 and bool(re.search(r"\d", v)),
}
_INPUT_TYPE = {"email": "email", "tel": "phone", "url": "url", "number": "number", "date": "date"}
_AUTOCOMPLETE = {"street-address": "address", "address-line1": "address", "postal-code": "postcode",
                 "tel": "phone", "email": "email", "url": "url"}
_LABEL = [(r"\bstreet\b|\baddress line\b", "address"), (r"\bpin ?code\b|\bpostal code\b|\bzip\b", "postcode"),
          (r"\bphone\b|\bmobile number\b", "phone"), (r"\be-?mail\b", "email")]


def infer_shape(entry_shape, input_type, autocomplete, label):
    """Entry's declared shape, else what the page declares (input type,
    autocomplete token), else label words. None = no clue -> nothing to check."""
    token = (autocomplete or "").split()[-1] if autocomplete else ""
    return (entry_shape or _INPUT_TYPE.get(input_type or "") or _AUTOCOMPLETE.get(token)
            or next((s for p, s in _LABEL if re.search(p, label or "", re.I)), None))


def shape_ok(shape, value, escape=None) -> bool:
    if not shape or value is None:
        return True
    if escape and str(value).strip().lower() == escape.strip().lower():
        return True                       # the page itself allowed this word
    check = SHAPES.get(shape)
    return True if check is None else check(str(value).strip())
