"""Answer a form question from the facts the bank holds, when its own entry has no value.

The retriever finds the stored facts most related to the question (your notice period, your CTC, ...);
the model reads what the form is asking — its wording, field type, options, today's date — and writes the
value to enter, using ONLY those facts. It can answer "NONE". There is no per-question rule: a last working
day, a joining date and "how soon can you start" all come from the same step.

Always a LIKELY fill (listed for review before submit): it is composed, not looked up."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

import numpy as np

from . import qbank

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
MIN_RELEVANCE = 0.40          # an entry less similar than this to the question is not offered as a fact
UNMATCHED_RELEVANCE = 0.50    # no entry matched the question at all: only clearly related facts are worth a model call
MAX_FACTS = 6


_FMT_TOKEN = {"dd": "%d", "d": "%-d", "mm": "%m", "m": "%-m", "mmm": "%b", "mmmm": "%B", "yyyy": "%Y", "yy": "%y"}
_FMT = re.compile(r"\b(d{1,2}|m{1,4}|y{2,4})([/.\-\s]+)(d{1,2}|m{1,4}|y{2,4})(?:\2(d{1,2}|m{1,4}|y{2,4}))?\b", re.I)


def date_format_from(text: str) -> str | None:
    """strftime pattern for a written format like 'DD/MM/YYYY', 'mm-dd-yy' or 'dd MMM yyyy'; None if there is none.
    It must name a year and be made of distinct parts, so 'MM/DD' or a stray 'dd' is not a format."""
    for m in _FMT.finditer(text or ""):
        toks = [t.lower() for t in (m.group(1), m.group(3), m.group(4)) if t]
        kinds = [t[0] for t in toks]
        if "y" in kinds and len(set(kinds)) == len(kinds):
            return m.group(2).join(_FMT_TOKEN[t] for t in toks if t in _FMT_TOKEN)
    return None


def related_facts(conn, question, *, embed, resolve, exclude=(), min_relevance=MIN_RELEVANCE,
                  topic=None) -> list[tuple[str, str, float]]:
    """[(entry question, value, relevance)] — stored facts related to `question`: the entries on the same
    topic as the matched entry (a notice period sits beside a joining date whatever the wording), then the
    ones whose wording is most similar. Only entries that hold a value."""
    facts, seen = [], set(exclude)

    def add(eid, score):
        entry = qbank.get_entry(conn, eid)
        value = resolve(entry) if entry else None
        if entry and value not in (None, "") and len(facts) < MAX_FACTS:
            facts.append((entry["question"], str(value), round(score, 3)))
        seen.add(eid)

    if topic:
        for (eid,) in conn.execute("SELECT id FROM qbank_entry WHERE topic=? AND status='active' ORDER BY id", (topic,)):
            if eid not in seen:
                add(eid, 1.0)
    rows = qbank.wordings(conn)
    if rows and (question or "").strip():
        sims = np.stack([v for _, _, v in rows]) @ embed([question])[0]
        best = {}
        for (_, eid, _), sim in zip(rows, sims):
            if eid not in seen and sim > best.get(eid, -2.0):
                best[eid] = float(sim)
        for eid, sim in sorted(best.items(), key=lambda kv: -kv[1]):
            if sim < min_relevance:
                break
            add(eid, sim)
    return facts


def _format_hint(f) -> str:
    kind = getattr(f, "input_type", "") or getattr(f, "kind", "") or "text"
    hint = {"date": "a date input", "number": "a number input: digits only"}.get(kind, f"a {kind} field")
    opts = list(getattr(f, "options", None) or [])
    return hint + (f"; choose exactly one of: {opts}" if opts else "")


_ASKS_DATE = re.compile(r"\bdate\b|\bdd\W?mm|\bmm\W?dd|yyyy|working day|last day|joining|available from|start day", re.I)
_NOT_COUNTED = re.compile(r"birth|\bdob\b|graduat|passing|issue|expiry|valid", re.I)


def asks_for_date(question, f) -> bool:
    """A calendar date counted from today (joining / last working day), not a date of the past."""
    if _NOT_COUNTED.search(question or ""):
        return False
    if (getattr(f, "input_type", "") or "") == "date" or "date" in str(getattr(f, "kind", "")):
        return True
    return bool(_ASKS_DATE.search(question or "")) or bool(date_format_from(_format_clues("", f)))


def build_prompt(question, f, facts, today: date, date_only: bool = False) -> str:
    listed = "\n".join(f"- {q} {v}" for q, v, _ in facts)
    if date_only:
        return ("You help fill in a job application form for the candidate, using ONLY the facts below.\n"
                f"Today's date: {today.isoformat()}\n"
                f'Form question: "{question}"\n\n'
                f"Facts about the candidate:\n{listed}\n\n"
                "The form wants a calendar date. Do NOT write a date. Work out how many whole days from today it falls, "
                "using the period the facts state (a notice period, a lead time; 'immediate' is 0). Unless the facts say the candidate is already serving notice, assume notice is given today, so a joining or last-working date is today plus the notice period. Reply with ONE JSON object "
                'and nothing else:\n  {"days_from_today": <whole number>}\n'
                'If the facts state no period: {"days_from_today": null}.')
    return ("You fill in a job application form for the candidate, using ONLY the facts below.\n"
            f"Today's date: {today.isoformat()}\n"
            f'Form question: "{question}"\n'
            f"The field is {_format_hint(f)}.\n\n"
            f"Facts about the candidate:\n{listed}\n\n"
            "Some facts may be unrelated to the question; ignore those. A date can be worked out from today's date and a "
            "period the facts state (a notice period, a lead time). Reply with ONE JSON object and nothing else:\n"
            '  {"value": "<the exact text, number or option to enter>"}\n'
            "or, ONLY when the field asks for a calendar date counted from today (today plus a period the facts state), "
            'give the count and do not write the date yourself:\n  {"days_from_today": <whole number>}\n'
            "A number field takes its number in value.\n"
            'If the facts do not determine the answer: {"value": null}. Never invent a fact.')


def _format_clues(question, f) -> str:
    return " ".join(filter(None, [question, getattr(f, "description", ""), getattr(f, "placeholder", "")]))


def _date_text(d: date, question: str, f) -> str:
    """What the page asks for: <input type=date> takes ISO whatever the label says; else a written format in the
    label, helper text or placeholder ('DD/MM/YYYY'); else ISO."""
    if (getattr(f, "input_type", "") or "") == "date" or getattr(f, "kind", "") in ("datepicker", "date_parts"):
        return d.isoformat()                                  # picked or split, not typed: the format on the page does not apply
    fmt = date_format_from(_format_clues(question, f))
    return d.strftime(fmt) if fmt else d.isoformat()


def _grounded(value: str, facts) -> bool:
    """A composed text value must come from the fact VALUES (not echo the question): its words appear in them, or all
    its numbers do. A model that answers 'mobile number' for 'Contact Number' invented nothing but says nothing."""
    norm = lambda t: " " + re.sub(r"[^a-z0-9]+", " ", str(t).lower()).strip() + " "
    v, text = norm(value), norm(" ".join(a for _, a, _ in facts))
    if not v.strip():
        return False
    if v in text:
        return True
    nums = re.findall(r"\d+", v)
    return bool(nums) and all(n in set(re.findall(r"\d+", text)) for n in nums)


def compose(question, f, facts, llm, today: date | None = None, date_only: bool | None = None) -> str | None:
    """The value the model chose from `facts`, or None. A date counted from today is worked out here, not by the model."""
    if llm is None or not facts:
        return None
    today = today or date.today()
    if date_only is None:
        date_only = asks_for_date(question, f)
    try:
        reply = _THINK.sub("", llm(build_prompt(question, f, facts, today, date_only)) or "")
    except Exception:
        return None
    i = reply.find("{")
    try:
        obj, _ = json.JSONDecoder().raw_decode(reply[i:]) if i >= 0 else ({}, 0)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    days = obj.get("days_from_today")
    if isinstance(days, (int, float)) and not isinstance(days, bool) and -3660 <= days <= 3660:
        if (getattr(f, "input_type", "") or getattr(f, "kind", "")) == "number":
            return str(int(days))                       # a number field wants the count itself, never a date
        return _date_text(today + timedelta(days=int(days)), question, f)
    if date_only:
        return None                                    # a date comes only from a day count, never from the model's own text
    value = obj.get("value")
    value = str(value).strip() if value not in (None, "") else ""
    ok = value and value.upper() != "NONE" and "\n" not in value and _grounded(value, facts)
    return value if ok else None
