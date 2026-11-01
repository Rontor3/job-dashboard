"""Answer a page SECTION BY SECTION with the whole page in view.

The bank, the rules and the résumé entries answer first, field by field, exactly as always (answering.answer_fields).
What they leave — short questions only; long prose stays with the drafter — is answered one section at a time, in page
order: one model call per section, briefed with
  - the page: every section's heading and its fields (label, type), so a small section still has its context;
  - the section: each field's label, type, required flag, options, format hint, what the box holds now, and the answers
    already decided for its neighbours;
  - your facts: every saved bank answer and your résumé.
Rules the reply must keep (checked in code, not trusted): an option field takes one of its options verbatim; nothing is
invented (null when the facts do not say); a value derived from a fact names the fact. A reply that breaks a rule is
dropped and the field stays open for the drafter or you. What a section is: browser/perception.py, SECTION RULES."""
from __future__ import annotations

import json
import re

from ..browser.form_model import asks_for_value, is_credential
from .claude_assist import first_json
from .mapper import FillDecision, _action_for_kind

_SHORT_KINDS = {"text", "combobox", "select", "radio_group", "date", "date_parts", "datepicker", "number", "tel", "email"}


def _short(f) -> bool:
    """A short answer: not prose (a textarea without a known purpose is an essay for the drafter)."""
    return f.kind in _SHORT_KINDS or (f.kind == "textarea" and bool(f.purpose))


def _key(f):
    return (f.section or "", f.row)


def _title(k) -> str:
    sec, row = k
    return f"{sec or 'Page'}" + (f" #{row + 1}" if row is not None and row >= 0 else "")


def _brief(fields) -> str:
    out, seen = [], []
    for f in fields:
        if f.kind == "button":
            continue
        k = _key(f)
        if k not in seen:
            seen.append(k)
            out.append(f"\n[{_title(k)}]")
        out.append(f"  - {f.label[:90]} ({f.kind})")
    return "\n".join(out)


def _facts(conn, profile_text: str) -> str:
    from ..memory import qbank
    rows = [f"- {e['question']} -> {e['answer']}" for e in qbank.entries(conn)
            if (e.get("answer") or "").strip() and e.get("topic") != "story"]
    return "SAVED ANSWERS:\n" + "\n".join(rows) + "\n\nRÉSUMÉ:\n" + (profile_text or "")


def prompt_for(section, page_fields, decided: dict, facts: str, job: dict) -> str:
    sec = []
    for f in section:
        line = {"id": f.ref, "label": f.label, "type": f.kind, "required": bool(f.required)}
        if f.options:
            line["options"] = f.options[:40]
        if f.placeholder:
            line["format"] = f.placeholder
        if f.value:
            line["box_holds_now"] = f.value[:80]
        sec.append(line)
    neighbours = [f"- {lbl}: {val}" for lbl, val in decided.items()]
    return (
        f"You fill a job application for the candidate below. Company: {job.get('company', '')}; "
        f"role: {job.get('title', '')}.\n\n"
        "THE WHOLE PAGE (every section and its fields, for context):" + _brief(page_fields) + "\n\n"
        f"NOW ANSWER ONLY THIS SECTION: [{_title(_key(section[0]))}]\n"
        + json.dumps(sec, ensure_ascii=False, indent=1) + "\n\n"
        "ALREADY ANSWERED ON THIS PAGE:\n" + ("\n".join(neighbours) or "- (none)") + "\n\n"
        + facts + "\n\n"
        "RULES:\n"
        "1. Use only the saved answers and the résumé. If they do not say, the value is null. Never invent a number, "
        "date, name, ID or address.\n"
        "2. A field with options takes exactly one option text, copied verbatim, or null.\n"
        "3. You may derive a value from a fact (an age range from the date of birth, a start date from the notice "
        "period counted from today, a Yes/No from a saved statement); say which fact in 'from'.\n"
        "4. Read each label in its section: 'Year' under 'Education #2' is that entry's year, not your career start.\n"
        "5. Answer every field of the section.\n\n"
        'Reply with JSON only: {"<id>": {"value": <string or null>, "from": "<fact used>"}, ...}')


def _valid(f, value) -> str | None:
    if value is None:
        return None
    v = str(value).strip()
    if not v or v.lower() in ("null", "none", "n/a", "unknown"):
        return None
    if f.options:
        from .screen_review import _coerce_option
        return _coerce_option(v, f.options)              # one of its options, or nothing
    return v


def answer_sections(needs, fields, decisions, ctx, llm, conn, profile_text):
    """(new decisions, needs still open). Only short questions are tried; credential / sensitive boxes never."""
    from .judgment import _is_sensitive
    label = {f.ref: f.label for f in fields}
    decided = {label.get(d.ref, d.ref)[:60]: str(d.value)[:60] for d in decisions if d.value not in (None, "")}
    todo = [f for f in needs if _short(f) and not is_credential(f) and not _is_sensitive(f) and not asks_for_value(f.label)]
    order, groups = [], {}
    for f in todo:
        k = _key(f)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(f)
    facts = _facts(conn, profile_text)
    job = ctx.get("job") or {}
    out, answered = [], set()
    for k in order:
        section = groups[k]
        try:
            reply = first_json(llm(prompt_for(section, fields, decided, facts, job)))
        except Exception as e:
            print(f"[section] {_title(k)!r}: model unavailable ({type(e).__name__})", flush=True)
            continue
        for f in section:
            item = reply.get(f.ref)
            value = _valid(f, item.get("value") if isinstance(item, dict) else item)
            if value is None:
                continue
            out.append(FillDecision(f.ref, f.kind, f.label, value, _action_for_kind(f.kind), "section",
                                    basis=f"section {_title(k)}: from {item.get('from', '?') if isinstance(item, dict) else '?'}"))
            answered.add(f.ref)
            decided[f.label[:60]] = value
        print(f"[section] {_title(k)!r}: {sum(f.ref in answered for f in section)}/{len(section)} answered", flush=True)
    return out, [f for f in needs if f.ref not in answered]


# --- Review: the whole section, every answer in view ------------------------------------------------------------------
# The bank matches one label at a time, so it cannot see that 'Location' under 'Work Experience #1 · Tata AIG' is the
# job's location, nor that Address Line 1, 2 and 3 all got the same full address (live 2026-10-31). Answers that came
# from an exact source stay locked; the rest are read again in their section and kept, changed or cleared.
_LOCKED = {"qbank", "resume", "form_instruction", "attestation", "human_prior", "decline_class", "revalidate"}
_REPEAT_OK = re.compile(r"confirm|re-?enter|repeat|verify|again", re.I)


def _norm(v) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(v).lower())


def duplicates(section_fields, by_ref) -> set:
    """Refs whose value already appears in an earlier, different box of the same section (all but the first holder).
    A box that asks to confirm / re-enter a value is meant to repeat it."""
    seen, dup = {}, set()
    for f in section_fields:
        d = by_ref.get(f.ref)
        # a long, many-word value (an address) is the one that gets smeared over boxes; a name or a city repeats
        # legitimately (Local Given Name = Given Name, Workday 2026-11-01)
        if d is None or not isinstance(d.value, str) or len(d.value.split()) < 3 or _REPEAT_OK.search(f.label or ""):
            continue
        k = _norm(d.value)
        if k in seen and seen[k] != f.label:
            dup.add(f.ref)
        seen.setdefault(k, f.label)
    return dup


def review_prompt(section, by_ref, ask, page_fields, facts, job) -> str:
    rows = []
    for f in section:
        d = by_ref.get(f.ref)
        rows.append({"id": f.ref, "label": f.label, "type": f.kind, "required": bool(f.required),
                     **({"options": f.options[:40]} if f.options else {}),
                     "proposed": (str(d.value)[:200] if d is not None else None),
                     **({"from": d.basis[:120]} if d is not None and getattr(d, "basis", "") else {}),
                     "review": f.ref in ask})
    return (
        f"You check a job application before it is sent. Company: {job.get('company', '')}; role: {job.get('title', '')}.\n\n"
        "THE WHOLE PAGE:" + _brief(page_fields) + "\n\n"
        f"THIS SECTION: [{_title(_key(section[0]))}] — each field with the answer proposed for it:\n"
        + json.dumps(rows, ensure_ascii=False, indent=1) + "\n\n" + facts + "\n\n"
        "For every field with \"review\": true, decide in the context of its section:\n"
        "- keep: the proposed answer is right for THIS field here.\n"
        "- change: it is wrong here; give the right value from the facts (an option field: one option verbatim).\n"
        "- clear: the field should stay empty (nothing in the facts fits, or it only repeats another field).\n"
        "Read each label in its section: a 'Location' inside a work-experience entry is where that job is, not your home "
        "address; 'Address Line 2/3' hold only what does not fit on line 1 (usually nothing); an answer copied from a "
        "neighbouring field is wrong unless the field asks to confirm it. An answer 'from' your saved answer to a question that "
        "asks the same thing as this field is right: keep it. Never invent.\n\n"
        'Reply with JSON only: {"<id>": {"verdict": "keep|change|clear", "value": <string or null>, "why": "<short>"}}')


def review_sections(fields, decisions, ctx, llm, conn, profile_text):
    """(decisions, cleared_fields): every section's answers read together; 'likely' / drafted / duplicated short answers
    are kept, changed or cleared. A cleared REQUIRED field is returned so it goes to the human."""
    by_ref = {d.ref: d for d in decisions}
    order, groups = [], {}
    for f in fields:
        if f.kind == "button":
            continue
        k = _key(f)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(f)
    facts, job, cleared = _facts(conn, profile_text), ctx.get("job") or {}, []
    for k in order:
        section = groups[k]
        dup = duplicates(section, by_ref)
        def locked(d):        # a résumé value is exact only when it came from that entry (entry_fields), not a mapping
            basis = getattr(d, "basis", "") or ""
            if basis.startswith("worked out for this job"):   # a rule turned the saved answer for this job (sponsorship
                return True    # 'No' in India): the model read the raw saved 'Yes' and put it back (Zoom, 2026-11-01)
            return d.source in _LOCKED and not (d.source == "resume" and "entry" not in basis)
        ask = {f.ref for f in section if f.ref in by_ref and _short(f) and f.kind != "textarea" and not is_credential(f)
               and (not locked(by_ref[f.ref]) or f.ref in dup)}
        if not ask:
            continue
        try:
            reply = first_json(llm(review_prompt(section, by_ref, ask, fields, facts, job)))
        except Exception as e:
            print(f"[review] {_title(k)!r}: model unavailable ({type(e).__name__})", flush=True)
            continue
        for f in section:
            if f.ref not in ask:
                continue
            item = reply.get(f.ref) if isinstance(reply.get(f.ref), dict) else {}
            verdict, why = str(item.get("verdict", "keep")).lower(), item.get("why", "")
            old = by_ref[f.ref]
            if verdict == "change" and (new := _valid(f, item.get("value"))) and _norm(new) != _norm(old.value):
                by_ref[f.ref] = FillDecision(f.ref, f.kind, f.label, new, old.action, "review",
                                             basis=f"section {_title(k)}: {why}"[:200])
                print(f"[review] {f.label[:40]!r}: {str(old.value)[:30]!r} -> {new[:30]!r} ({why[:60]})", flush=True)
            elif verdict == "clear" or (f.ref in dup and verdict != "keep"):
                del by_ref[f.ref]
                if f.required:
                    cleared.append(f)
                print(f"[review] {f.label[:40]!r}: cleared {str(old.value)[:30]!r} ({why[:60]})", flush=True)
    return list(by_ref.values()), cleared
