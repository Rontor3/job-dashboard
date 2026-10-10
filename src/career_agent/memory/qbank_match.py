"""Question-bank retrieval: one page field -> (Match, value).

Faithfulness rule: the LLM may only choose WHICH shortlisted entry a question
is (a letter or NONE). Every value comes from the bank, the profile, the job
row, or a deterministic rule (qbank_rules). Bands:
  CONFIDENT  fill                        exact wording, or clear top match
  LIKELY     fill + flag for review      LLM-picked, polarity or shape doubt
  NONE       leave to rules/judgment/you below FLOOR, LLM said none, no answer
Spec: docs/superpowers/specs/2026-09-26-question-bank-design.md §2."""
from __future__ import annotations

import re
from dataclasses import dataclass, field as _field

import numpy as np

from . import qbank
from .qbank_rules import RULES, RuleCtx, infer_shape, shape_ok

# Starting values — re-derive with `scripts/qbank.py calibrate`.
FLOOR = 0.55          # top score below this = no match (result discarded)
MARGIN = 0.04         # top entry must lead the runner-up by this to skip the LLM
DEFAULT_HIGH = 0.87   # runtime value: agent setting qbank_confident_min / 100

CONFIDENT, LIKELY, NONE = "confident", "likely", "none"

_ESCAPE = re.compile(
    r'''\b(type|enter|write|put|respond with)\b[^"“']{0,20}["“']([^"”']{2,30})["”']''', re.I)
_POLARITY = {"not", "no", "without", "never", "ever", "require", "required", "need"}
# Contrasting qualifiers that make two otherwise identical questions different ("current" vs "expected" salary).
# A small embedding model scores them near-identical, so a clash is never auto-confident.
_QUALIFIERS = {"now": {"current", "present", "existing", "last", "previous", "today"},
               "later": {"expected", "desired", "target", "expecting", "preferred", "future", "minimum", "maximum"}}
_NAME_LIKE = re.compile(r"^[\w.-]+\[")
_OPTION_WORDS = {"yes", "no", "true", "false", "n/a", "na", "-"}
_THINK = re.compile(r"<think>.*?</think>", re.S)
_LETTER = re.compile(r"^\(?([abc])\)?(?:[\s.:)]|$)")


@dataclass
class Match:
    band: str
    entry_id: str | None = None
    score: float = 0.0
    kind: str = "none"                                  # exact | shortlist | llm | none
    candidates: list = _field(default_factory=list)     # [(entry_id, score)] top 3
    escape: str | None = None
    note: str = ""


def split_escape(label: str, description: str = ""):
    """Drop the 'type "X" if …' sentence from the question and return X
    separately. Helper text is scanned for X only, never matched on."""
    escape, kept = None, []
    for s in re.split(r"(?<=[.?!])\s+", (label or "").strip()):
        m = _ESCAPE.search(s)
        if m:
            escape = escape or m.group(2).strip()
        elif s:
            kept.append(s)
    if escape is None:
        m = _ESCAPE.search(description or "")
        escape = m.group(2).strip() if m else None
    return " ".join(kept).strip(), escape


_FORMAT_HINT = re.compile(r"\(?\b(?:dd|mm|yyyy|yy)(?:[/.\-](?:dd|mm|yyyy|yy)){1,2}\b\)?", re.I)


def without_format_hint(question: str) -> str:
    """'Joining date (dd/mm/yyyy)' asks the same thing as 'Joining date': the format only shapes the answer."""
    q = re.sub(r"\s+", " ", _FORMAT_HINT.sub("", question or "")).strip(" -:(,;")
    q = re.sub(r"(?:\b(?:use|in|the|date)\s+)*\bformat\s*:?\s*$", "", q, flags=re.I).strip(" -:(,;")
    return q or question


def is_junk(f) -> bool:
    """Not a question: empty/placeholder (perception's own test), a bare option
    word, an input name like cards[uuid][field3], or one of its own options."""
    from ..browser.perception import is_unlabeled
    label = (f.label or "").strip()
    key = qbank.norm(label)
    return (is_unlabeled(f) or key in _OPTION_WORDS or bool(_NAME_LIKE.match(label))
            or key in {qbank.norm(o) for o in (f.options or [])})


def _polarity(text: str) -> set:
    return {t for t in re.findall(r"[a-z]+", (text or "").lower()) if t in _POLARITY}


def _qualifiers(text: str) -> set:
    words = set(re.findall(r"[a-z]+", (text or "").lower()))
    return {k for k, v in _QUALIFIERS.items() if words & v}


def qualifier_clash(question: str, wording: str) -> bool:
    """Both name a qualifier and they point opposite ways (current vs expected)."""
    a, b = _qualifiers(question), _qualifiers(wording)
    return bool(a and b and a != b)


def _slot_note(entry) -> str:
    """An entry with slots (skill, company) stands for every instance of it: 'with this skill' is the same
    question as 'with Docker'. Say so, or a strict matcher answers NONE for any named one."""
    return "".join(f' [the {s} can be any specific {s} the form names]' for s in entry.get("slots") or [])


def llm_pick(question, entry_ids, conn, llm):
    """Which shortlisted entry is this question? The reply must be a letter or
    NONE; anything else counts as NONE (flag, never guess)."""
    if llm is None or not entry_ids:
        return None
    ents = [qbank.get_entry(conn, e) for e in entry_ids[:3]]
    prompt = ("A job application form asks:\n"
              f'"{question}"\n\n'
              "Which ONE of these questions asks exactly the same thing (same meaning, "
              "same yes/no direction)? Reply with the letter only, or NONE if none match.\n\n"
              + "\n".join(f"({'abc'[i]}) {e['question']}{_slot_note(e)}" for i, e in enumerate(ents))
              + "\n\nAnswer:")
    try:
        reply = _THINK.sub("", llm(prompt) or "").strip().lower()
    except Exception:
        return None
    m = _LETTER.match(reply)
    if not m:
        return None
    i = "abc".index(m.group(1))
    return ents[i]["id"] if i < len(ents) else None


def match_question(conn, question, *, embed, llm=None, high=DEFAULT_HIGH,
                   floor=FLOOR, margin=MARGIN) -> Match:
    eid = qbank.exact(conn, question)
    if eid:
        return Match(CONFIDENT, eid, 1.0, "exact", [(eid, 1.0)])
    rows = qbank.wordings(conn)
    if not rows or not (question or "").strip():
        return Match(NONE)
    sims = np.stack([v for _, _, v in rows]) @ embed([question])[0]
    best, best_text = {}, {}
    for (text, e, _), s in zip(rows, sims):
        if s > best.get(e, -2.0):
            best[e], best_text[e] = float(s), text
    top = sorted(best.items(), key=lambda kv: -kv[1])[:3]
    cands = [(e, round(s, 3)) for e, s in top]
    s1 = top[0][1]
    s2 = top[1][1] if len(top) > 1 else 0.0
    if s1 < floor:
        return Match(NONE, None, s1, "none", cands, note="below floor")
    if s1 >= high and s1 - s2 >= margin and not qualifier_clash(question, best_text[top[0][0]]):
        m = Match(CONFIDENT, top[0][0], s1, "shortlist", cands)
    else:
        pick = llm_pick(question, [e for e, s in top if s >= floor], conn, llm)
        if pick is None:
            return Match(NONE, None, s1, "llm", cands,
                         note="llm: none" if llm else "ambiguous, no llm")
        m = Match(LIKELY, pick, best[pick], "llm", cands)
    if _polarity(question) != _polarity(best_text[m.entry_id]):
        m.band, m.note = LIKELY, "polarity differs"
    return m


def resolve_value(conn, entry, *, question, escape, job, contact, options=(), _depth=0):
    """Entry -> answer string, or None (unanswered / rule can't decide).
    Precedence: rule > profile_ref > stored answer."""
    if entry.get("rule"):
        fn = RULES.get(entry["rule"])
        if fn is None or _depth > 2:
            return None

        def bank(eid):
            other = qbank.get_entry(conn, eid)
            return None if other is None else resolve_value(
                conn, other, question=other["question"], escape=None,
                job=job, contact=contact, _depth=_depth + 1)
        return fn(RuleCtx(question, entry.get("answer"), escape, job or {}, bank,
                          options=list(options), synonyms=entry.get("synonyms") or {},
                          entry_id=entry.get("id") or ""))
    if entry.get("profile_ref"):
        v = (contact or {}).get(entry["profile_ref"])
        if v is None or str(v).strip() == "":
            return None
        v_str = str(v).strip().lower()
        if entry.get("atype") == "bool":
            if v_str in {"1", "true", "yes", "y"}:
                return "Yes"
            elif v_str in {"0", "false", "no", "n"}:
                return "No"
        return str(v).strip()
    a = entry.get("answer")
    return a if a and a.strip() else None


def fit_option(label, value, options, synonyms, llm=None):
    """Canonical value -> one of the page's options, or None (flag). No static
    options (text box, or a combobox whose options load live) -> the value."""
    if not options:
        return value
    by_norm = {qbank.norm(o): o for o in options}
    for cand in [value, *(synonyms or {}).get(value, [])]:
        if qbank.norm(cand) in by_norm:
            return by_norm[qbank.norm(cand)]
    from ..orchestrator.screen_review import _coerce_option
    hit = _coerce_option(value, options)
    if hit is None and llm is not None:
        from ..orchestrator.judgment import match_value_to_option
        hit = match_value_to_option(label, value, options, llm)
    return hit


def _compose_from_facts(conn, f, question, entry, embed, llm, job, contact):
    """(value, 'fact1; fact2') written by the model from the bank's related facts, or (None, None).
    Only when the matched entry holds no value of its own; never for sensitive or free-essay fields."""
    from ..orchestrator.judgment import _is_sensitive
    from . import qbank_compose
    if llm is None or f.kind == "textarea" or _is_sensitive(f):
        return None, None
    if entry is None and f.purpose:
        return None, None          # an unmatched field with a known purpose (phone, email...) is the rule mapper's job
    yes_no = {qbank.norm(o) for o in (f.options or [])} <= {"yes", "no"} and bool(f.options)
    if yes_no or (entry and entry.get("atype") == "bool"):
        return None, None          # a Yes/No is a statement about you, never something to work out from other facts
    facts = qbank_compose.related_facts(
        conn, question, embed=embed, exclude={entry["id"]} if entry else (),
        min_relevance=qbank_compose.MIN_RELEVANCE if entry else qbank_compose.UNMATCHED_RELEVANCE,
        topic=entry.get("topic") if entry else None,
        resolve=lambda e: resolve_value(conn, e, question=e["question"], escape=None, job=job, contact=contact))
    value = qbank_compose.compose(question, f, facts, llm,
                                  date_only=bool(entry and entry.get("atype") == "date") or qbank_compose.asks_for_date(question, f))
    return (value, "; ".join(q for q, _, _ in facts)) if value else (None, None)


def answer_field(conn, f, *, embed, llm=None, job=None, contact=None, high=DEFAULT_HIGH):
    if f.kind in ("file", "button") or f.purpose == "attestation":
        return Match(NONE, note="not a bank field"), None
    question, escape = split_escape(f.label, f.description)
    if is_junk(f) or not question:
        return Match(NONE, note="junk label"), None
    m = match_question(conn, without_format_hint(question), embed=embed, llm=llm, high=high)
    m.escape = escape
    if m.entry_id is None:
        value, composed = _compose_from_facts(conn, f, question, None, embed, llm, job, contact)
        fitted = fit_option(f.label, value, f.options, None, llm) if value else None
        if fitted is None:
            return m, None
        m.band, m.kind, m.note = LIKELY, "composed", f"composed from your saved facts: {composed}"
        return m, fitted
    entry = qbank.get_entry(conn, m.entry_id)
    value = resolve_value(conn, entry, question=question, escape=escape, job=job, contact=contact,
                           options=f.options)
    composed = None
    if value is None:
        value, composed = _compose_from_facts(conn, f, question, entry, embed, llm, job, contact)
        if value is None:
            m.band, m.note = NONE, "no answer for entry"
            return m, None
    shape = infer_shape(entry["shape"], getattr(f, "input_type", ""),
                        getattr(f, "autocomplete", ""), f.label)
    if not shape_ok(shape, value, escape):
        m.band, m.note = LIKELY, f"shape {shape} failed"
    fitted = fit_option(f.label, value, f.options, entry["synonyms"], llm)
    if fitted is None:
        m.band, m.note = NONE, "no option fits"
    elif composed:
        m.band, m.note = LIKELY, f"composed from your saved facts: {composed}"     # written, not looked up: review it
    return m, fitted
