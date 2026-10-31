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
