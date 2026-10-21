"""Question-bank retrieval: one page field -> (Match, value).

Faithfulness rule: the LLM may only choose WHICH shortlisted entry a question
is (a letter or NONE). Every value comes from the bank, the profile, the job
row, or a deterministic rule (qbank_rules). Bands:
  CONFIDENT  fill                        exact wording, or clear top match
  LIKELY     fill + flag for review      LLM-picked, polarity or shape doubt
  NONE       leave to rules/judgment/you below FLOOR, LLM said none, no answer
Spec: docs/superpowers/specs/2026-09-26-question-bank-design.md §2."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as _field

import numpy as np

from . import qbank
from .qbank_rules import RULES, RuleCtx, dial_label, infer_shape, shape_ok

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
                          options=list(options), synonyms=entry.get("synonyms") or {}))
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
    options (text box, or a combobox whose options load live) -> the value.
    Order: (1) exact wording of the value or a stored synonym; (2) the
    vocabulary bridge — deterministic containment against the site's own
    phrasing; (3) the orchestrator's option coercer; (4) the LLM, last."""
    if not options:
        return value
    by_norm = {qbank.norm(o): o for o in options}
    cands = [value, *(synonyms or {}).get(value, [])]
    for cand in cands:
        if qbank.norm(cand) in by_norm:
            return by_norm[qbank.norm(cand)]
    for cand in cands:                        # bridge: same event, site's wording
        hit = bridge_option(cand, options)
        if hit is not None:
            return hit
    from ..orchestrator.screen_review import _coerce_option
    hit = _coerce_option(value, options)
    if hit is None and llm is not None:
        from ..orchestrator.judgment import match_value_to_option
        hit = match_value_to_option(label, value, options, llm)
    return hit


# ── the vocabulary bridge (fit_option rung 2) ────────────────────────────────
_GAP = re.compile(r"[^a-z0-9+]+")            # punctuation/space -> one space; '+', letters, digits stay

_SOLITUDE = ("self", "not", "no", "none", "non", "un", "anti", "without", "never",
             "former", "ex", "refuse", "decline", "declined", "unavailable")


def vocab_norm(text: str) -> str:
    """'India (+91)' -> 'india +91': casefolded, punctuation to single spaces,
    '+' kept so a dial code means itself ('+91' never reads as '91') and can
    never band-match another number crossing the word boundary."""
    s = _GAP.sub(" ", str(text or "").casefold())
    s = re.sub(r"\+\s+(?=\w)", "+", s)       # '+ 91' -> '+91'
    return " ".join(s.split())


def _knows(inner_norm: str, outer_norm: str) -> bool:
    """The inner phrase occurs inside `outer_norm` word-aligned, and the tokens
    around it add wording, never meaning: 'LinkedIn', 'Other' are benign
    qualifiers; 'Self-Employed' or 'Not employed' are different answers."""
    a, b = inner_norm.split(), outer_norm.split()
    for i in range(len(b) - len(a) + 1):
        if b[i:i + len(a)] == a:
            flanks = b[:i] + b[i + len(a):]
            return not (set(_SOLITUDE) & set(flanks))
    return False           # not word-aligned inside outer after all: distrust it


def bridge_option(value, options) -> str | None:
    """The deterministic containment rung of fit_option: the option and the
    value share a phrasing — one contains the other at a word boundary
    ('+91' in 'India (+91)', 'Job Board' in 'Job board (LinkedIn)', 'Other'
    inside a stored 'Other - please specify'). Returns the option, or None:

    * exactly one survivor -> it;
    * several survivors of the SAME relation -> the least-qualified one:
      shortest option when qualifiers were added to the value, longest when the
      option is the qualifier-free pith (screen_review already prefers the
      longest subset for that direction);
    * survivors that mean different things — both directions at once, or a
      polarity-bearing qualifier — -> None: let the existing matchers decide,
      this rung never votes on a meaning it can't read."""
    vn = vocab_norm(value)
    if not vn:
        return None
    vf = f" {vn} "
    wider, narrower = [], []
    for o in options or []:
        on = vocab_norm(o)
        if not on or on == vn:
            continue                          # equal forms: rung 1 owned it
        if vf in f" {on} ":
            wider.append((o, on))
        elif f" {on} " in vf:
            narrower.append((o, on))
    if wider and narrower:
        return None                           # both directions relate: different things
    if wider:
        ok = [o for o, on in wider if _knows(vn, on)]
        return min(ok, key=len) if ok else None
    ok = [o for o, on in narrower if _knows(on, vn)]
    return max(ok, key=len) if ok else None


# ── typed fills without options (the empty combobox / plain text box) ────────
_DIAL_CODE = re.compile(r"\+\d{1,4}\b")      # a stored dial code always carries its '+'
_DIAL_VALUE = re.compile(r"\+?[1-9]\d{0,3}", re.A)   # a dial value: short digits, never 0-led


def _stored_dial(*texts) -> str | None:
    """The one dial code ('+91') these stored texts hold: a value that is only
    a country name ('India') can still be written as the code the bank's own
    answer/synonyms record. Several distinct codes -> None: don't guess."""
    dials = []
    for text in texts:
        if not text:
            continue
        s = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
        for t in _DIAL_CODE.findall(s):
            if t not in dials:
                dials.append(t)
        if len(dials) > 1:
            return None
    return dials[0] if len(dials) == 1 else None


def _typed_shape(shape, value, entry, label, has_options) -> tuple[str | None, str | None, str]:
    """(value, basis note, gate) for a fill that goes out TYPED — because the
    field offers nothing to fit (an options_json-empty combobox, a plain box)
    or as the raw form before the options are matched.

    gate:

    'proceed'           the value now fits the field's real form: the dial code
                        a code-asking label wants, as stored, completed with
                        its '+', or rescued from the entry's own stored
                        answer/synonyms; nothing is invented and '+' is read,
                        never stripped;
    'refuse'            an empty-options field with a phone-shaped value it
                        cannot take — dead on arrival, so the field escalates
                        with a crisp basis instead of a doomed typed fill;
    'proceed-flagged'   everything else: with no options the site's own
                        validator still gets the value, band as today.

    Real-world knowledge ('Senior Data Scientist' <-> a category option) is
    NEVER spent here — the judgment tier keeps that job."""
    v = str(value).strip()
    dial_intent = dial_label(label)
    if shape != "phone" and not dial_intent:
        return v, None, "proceed-flagged"
    if not v:
        return None, "the stored answer is blank", "refuse"
    if dial_intent:
        if _DIAL_VALUE.fullmatch(v):                      # '+91'; a bare '91' gets its '+' back
            dial = v if v.startswith("+") else f"+{v}"
            return dial, (None if dial == v else f"dial code written as {dial!r}"), "proceed"
        dial = _stored_dial(v, entry.get("answer"), entry.get("synonyms"))
        if dial:
            return dial, f"dial code {dial!r} read from the stored answer ({v!r} alone is not a code)", "proceed"
        if has_options:
            return v, None, "proceed-flagged"             # the options will be asked to say what they mean
        return None, f"{v!r} is not a dial code and the stored answer supplies none", "refuse"
    if _DIAL_VALUE.fullmatch(v) and not has_options:
        return None, (f"{v!r} reads as a dial code but this label asks for a full "
                      "phone number"), "refuse"
    if not has_options:
        return None, f"{v!r} is not a value this field's shape can take", "refuse"
    return v, None, "proceed-flagged"


def _yes_no_from_facts(f, question, facts, llm):
    """A Yes/No question the bank holds no Yes/No answer for ("Do you speak English?" vs the stored English level
    "Fluent" and languages "Hindi, English"): the model reads ONLY those saved answers and says Yes, No, or NONE when
    they do not settle it. Never for a sensitive field or without a model; the caller marks the fill LIKELY."""
    from ..orchestrator.judgment import _is_sensitive
    opts = f.options or []
    if llm is None or not facts or {qbank.norm(o) for o in opts} != {"yes", "no"} or _is_sensitive(f):
        return None
    saved = "\n".join(f"- {q} -> {v}" for q, v, _ in facts)
    try:
        reply = llm("A job application asks the candidate a Yes/No question. Using ONLY the saved answers below, "
                    "reply with exactly Yes, No, or NONE if they do not settle it.\n"
                    f"Form question: {question}\nSaved answers:\n{saved}\nReply:")
    except Exception:
        return None
    word = re.sub(r"[^a-z]", "", (re.sub(r"<think>.*?</think>", "", reply or "", flags=re.S).strip().split() or [""])[0].lower())
    return {"yes": "Yes", "no": "No"}.get(word)


def _yes_no_from_value(f, question, entry, value, llm):
    """The matched entry holds a non-Yes/No answer: read it. Never for a bool entry (its Yes/No is stated)."""
    if entry.get("atype") == "bool":
        return None
    return _yes_no_from_facts(f, question, [(entry["question"], str(value), 1.0)], llm)


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


_TOTAL_EXP = re.compile(r"\b(total|overall)\b[^?]{0,40}\bexperience\b", re.I)


def _rating_from_level(conn, f, m, job, contact):
    """(option, level) for "Rate your English on a scale of 1 to 5": the options are a plain number scale and the nearest
    bank entry holds a level word (Fluent) — position it on the scale: native/fluent top, professional one below, basic
    bottom, conversational between. None for anything else."""
    from .facts import LEVELS, level
    nums = [o.strip() for o in f.options or []]
    if len(nums) < 3 or not all(o.isdigit() for o in nums) or not re.search(r"\b(rate|scale|rating)\b", f.label or "", re.I):
        return None
    for eid, score in m.candidates:
        entry = qbank.get_entry(conn, eid)
        lv = level(resolve_value(conn, entry, question=entry["question"], escape=None, job=job, contact=contact)) if entry and score >= 0.7 else None
        if lv:
            ordered = sorted(nums, key=int)
            top = {"native": 1, "fluent": 1, "professional": 2, "conversational": 3, "basic": len(ordered)}[lv]
            return (ordered[-top] if lv != "basic" else ordered[0]), lv
    return None


def answer_field(conn, f, *, embed, llm=None, job=None, contact=None, high=DEFAULT_HIGH):
    if f.kind in ("file", "button") or f.purpose == "attestation":
        return Match(NONE, note="not a bank field"), None
    question, escape = split_escape(f.label, f.description)
    if is_junk(f) or not question:
        return Match(NONE, note="junk label"), None
    if getattr(f, "purpose", None) == "skill_years" and qbank.get_entry(conn, "skill_years"):
        # "Years of experience with <skill>" is recognised by its shape (form_model),
        # so any skill named in the user's table answers — no per-wording seed needed.
        m = Match(CONFIDENT, "skill_years", 1.0, "structure")
    else:
        m = match_question(conn, without_format_hint(question), embed=embed, llm=llm, high=high)
    m.escape = escape
    if m.entry_id is None and _TOTAL_EXP.search(question) and any(re.search(r"\d", o) for o in f.options or []):
        # "Total full-time experience in Data Scientist / AI / ML (internships not included)?" with year-range options:
        # the qualifiers keep the model from calling it the total-experience question, but it is that question.
        hit = next((e for e, sc in m.candidates if e == "total_experience_years" and sc >= 0.6), None)
        if hit:
            m = Match(LIKELY, hit, dict(m.candidates)[hit], "structure", m.candidates, escape, "total experience by its shape")
    if m.entry_id is None and (pick := _rating_from_level(conn, f, m, job, contact)):
        m.band, m.kind, m.note = LIKELY, "composed", f"scale position of your saved level: {pick[1]}"
        return m, pick[0]
    if m.entry_id is None:
        value, composed = _compose_from_facts(conn, f, question, None, embed, llm, job, contact)
        fitted = fit_option(f.label, value, f.options, None, llm) if value else None
        if fitted is None and not value and not f.purpose:
            from . import qbank_compose
            facts = qbank_compose.related_facts(
                conn, question, embed=embed, min_relevance=qbank_compose.UNMATCHED_RELEVANCE,
                resolve=lambda e: resolve_value(conn, e, question=e["question"], escape=None, job=job, contact=contact))
            fitted = _yes_no_from_facts(f, question, facts, llm)
            if fitted is not None:
                m.band, m.kind, m.note = LIKELY, "composed", f"Yes/No read from your saved answers: {'; '.join(q for q, _, _ in facts)}"
                return m, fitted
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
    escaped = bool(escape) and str(value).strip().lower() == str(escape).strip().lower()
    if not escaped and (dial_label(f.label) or not shape_ok(shape, value, escape)):
        shaped, how, gate = _typed_shape(shape, value, entry, f.label, bool(f.options))
        if gate == "refuse":
            # Empty options and no deterministic way to shape the value: the
            # fill would be typed straight into a field that can't take it.
            # Today's unsupported signal — no value — sends the field up with
            # this basis instead of a 'did not take' the human reads later.
            m.band = NONE
            m.note = (f"shape {shape} failed, no options to fit: {how}" if not m.note
                      else f"{m.note}; shape {shape} failed, no options to fit: {how}")
            return m, None
        if gate == "proceed":
            if how:
                m.note = f"{m.note}; {how}" if m.note else how
            value = shaped
        else:
            m.band, m.note = LIKELY, f"shape {shape} failed"
    fitted = fit_option(f.label, value, f.options, entry["synonyms"], llm)
    if fitted is None:
        fitted = _yes_no_from_value(f, question, entry, value, llm)
        if fitted is not None:
            m.band, m.note = LIKELY, f"Yes/No read from your saved answer '{entry['question']}': {value}"
            return m, fitted
        m.band, m.note = NONE, "no option fits"
    elif composed:
        m.band, m.note = LIKELY, f"composed from your saved facts: {composed}"     # written, not looked up: review it
    return m, fitted
