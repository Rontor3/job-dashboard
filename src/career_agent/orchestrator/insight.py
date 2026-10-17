"""Reading an insight: the applicant's note beside a wrong or blank answer → which CAUSE it names, and the general
lesson behind it.

Wrong answers come from a few causes, each with its own lever (and its own store when accepted, see
memory/lessons.py):

    trust     the answer is right; it was only held back as unsure
    fact      a fact about the applicant is missing or wrong (the note states it)
    lookup    the answer is already stored under other words
    policy    a standing default for a kind of question (consent boxes, "how did you hear", unknown skill = 0)
    derive    the answer is worked out: compare the job with the applicant, convert a unit, compute a date
    shape     the field wants one part / unit / format of a fact (the currency, the dial code, only the number)
    identify  the field's label doesn't say what it asks; the note names it
    scope     an essay used the wrong material (e.g. no projects for a general/hypothetical question)
    guide     anything else about how to write it (tone, length, never invent numbers)

The model never sees the current answer's value — only the field, where the answer came from, and the notes.
"""
from __future__ import annotations

import json
import re

LEVERS = ("trust", "fact", "lookup", "policy", "derive", "shape", "identify", "scope", "guide")
APPLIES = ("question", "similar", "long", "short")

PROMPT = """{context}

The applicant reviewed one field the application agent filled (or left blank) and wrote a note about it.
Your job: name the CAUSE of the problem and the general lesson behind the note — not just this one answer.

Field ({kind}): {label}{options}
Where the agent's answer came from: {origin}
Applicant's note(s), latest last:
{notes}

Causes (pick ONE lever):
  trust    - the answer is right, it was only held back as unsure ("this is correct", "yes that's my email")
  fact     - a fact about the applicant is missing or wrong; the note states the value ("my current CTC is 25 LPA")
  lookup   - the answer is already stored under other words ("it's in my answers as total experience")
  policy   - a standing default for this kind of question ("always acknowledge privacy notices", "say LinkedIn for
             how did you hear", "a skill I don't list is 0 years", "opt out of marketing emails")
  derive   - the answer must be worked out ("compare the job's city with mine", "convert my salary to USD",
             "count years since my career start")
  shape    - right fact, wrong part or format ("this box wants only the currency", "just the number, no LPA",
             "only the dial code")
  identify - the label doesn't say what the field asks; the note names it ("this is the end date of my last job")
  scope    - an essay drew on the wrong material ("don't use my projects here, answer from general knowledge")
  guide    - any other instruction on how to write it ("shorter", "never invent metrics", "no greeting line")

Reply with JSON only:
{{"lever": "...",
  "value": "the answer or default the note states or implies (REQUIRED for fact and policy; for a tick box: Yes = tick,
            No = leave unticked; 'always acknowledge' = Yes), else null",
  "query": "for lookup: the words it is stored under, else null",
  "meaning": "for identify: what the field actually asks, else null",
  "concept": "the KIND of question this is, generic, e.g. 'willingness to work in the job's city'",
  "rule": "the lesson as 'When <condition>, <do this>' — generic: no company names, no personal values",
  "why": "why the applicant said it, in one sentence",
  "applies_to": "question | similar | long | short"}}
applies_to: question = only this wording; similar = questions about the same concept; long = every essay answer;
short = every short field. Prefer the narrowest that still captures the lesson."""

_BROAD = ("long", "short")            # never chosen for you: a lesson starts at its concept; you widen it


def _parse(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    i = text.find("{")
    if i < 0:
        return {}
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[i:])
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _generic(text, company: str):
    if not isinstance(text, str) or not text.strip():
        return None
    text = text.strip()[:400]
    return re.sub(re.escape(company), "the employer", text, flags=re.I) if company else text


def validate(d: dict, notes: list[str], company: str = "") -> dict:
    """A usable directive whatever the model replied: an unknown lever is a guide, a bad scope is the narrowest."""
    lever = d.get("lever") if d.get("lever") in LEVERS else "guide"
    scope = d.get("applies_to") if d.get("applies_to") in APPLIES else "question"
    out = {"lever": lever,
           "applies_to": "similar" if scope in _BROAD else scope,
           "concept": _generic(d.get("concept"), company),
           "rule": _generic(d.get("rule"), company) or (notes[-1].strip()[:400] if notes else None),
           "why": _generic(d.get("why"), company)}
    for k in ("value", "query", "meaning"):
        v = d.get(k)
        out[k] = str(v).strip()[:500] if v not in (None, "", "null") else None
    if lever in ("fact", "policy") and not out["value"]:
        out["lever"] = "guide"                            # a value lever with no value is just an instruction
    return out


def checkbox_default(d: dict, kind: str) -> dict:
    """A tick box has two answers, so an instruction about one IS a default: 'always acknowledge' -> policy Yes."""
    if kind != "checkbox" or d["lever"] not in ("guide", "policy") or d.get("value"):
        return d
    text = f"{d.get('rule') or ''} {d.get('concept') or ''}".lower()
    no = any(w in text for w in ("untick", "don't tick", "do not tick", "opt out", "decline", "leave unticked", "never"))
    yes = any(w in text for w in ("acknowledge", "agree", "accept", "tick", "consent", "confirm", "opt in"))
    if no or yes:
        return {**d, "lever": "policy", "value": "No" if no else "Yes"}
    return d


def interpret(field: dict, notes: list[str], job: dict, llm) -> dict:
    """field: {label, kind, options, origin}. → validated directive (see validate)."""
    from ..memory.facts import applicant_context
    opts = field.get("options") or []
    prompt = PROMPT.format(
        context=applicant_context(job or {}), kind=field.get("kind") or "text", label=field.get("label") or "",
        options=f"\nIts options: {list(opts)[:40]}" if opts else "", origin=field.get("origin") or "unknown",
        notes="\n".join(f"{i + 1}. {n.strip()}" for i, n in enumerate(notes) if n and n.strip()))
    try:
        raw = _parse(llm(prompt))
    except Exception as e:                                # the model is down: the note itself is the instruction
        raw = {"why": f"model unavailable ({type(e).__name__})"}
    return validate(raw, notes, (job or {}).get("company") or "")
