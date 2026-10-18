"""Answer a form SECTION's fields together: one local call (values) and one Haiku call (plans, schema only) per section,
instead of several calls per field.

A section is the fields under one heading of the page, per repeated entry (Field.section / Field.row, from
perception): "Contact Information", "Education #2", "Work authorization". Each field goes in with what the model needs
to fill it — its label, kind, whether it is required, its options and its format (input type, placeholder, length,
unit) — so the model reads the fields in context and answers them in one reply.

The checks per field are exactly the one-field path's (memory/factcards.py): the local reader's value must fit the
options / shape and be grounded in the card it cites; the Haiku plan is run over the stored facts; the two must agree
(factcards.gate). Plans are cached per wording (PlanCache), so a wording seen before costs no Haiku call at all.
Values never leave the machine: Haiku sees field labels, options and fact NAMES only.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

from . import facts as F
from .factcards import _show, check_local, gate, question_of

MAX_PER_PACKET = 12           # ponytail: fixed split of a long section; tune if replies start dropping fields
MAX_CARDS = 30
MAX_OPTIONS = 40


def _key(f):
    return (f.section or "", f.row)


def packets(fields) -> list[list]:
    """Fields grouped by (section, entry row) in page order, long sections split."""
    order, groups = [], {}
    for f in fields:
        k = _key(f)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(f)
    out = []
    for k in order:
        g = groups[k]
        out += [g[i:i + MAX_PER_PACKET] for i in range(0, len(g), MAX_PER_PACKET)]
    return out


def title(packet) -> str:
    f = packet[0]
    return (f.section or "Form") + (f" — entry {f.row + 1}" if f.row >= 0 else "")


def fmt(f) -> str:
    """What shape the answer must take, from the page itself."""
    bits = []
    if getattr(f, "input_type", "") and f.input_type not in ("text", ""):
        bits.append(f.input_type)
    if getattr(f, "placeholder", ""):
        bits.append(f"looks like '{f.placeholder}'")
    if getattr(f, "unit", ""):
        bits.append(f"in {f.unit}")
    if getattr(f, "max_length", 0):
        bits.append(f"max {f.max_length} chars")
    return ", ".join(bits)


def _field_line(i, f, guidance="") -> str:
    q = question_of(f.label, f.ref)
    line = f"F{i}. ({f.kind}{', required' if f.required else ''}) {q}"
    if f.options:
        line += f" | options: {list(f.options)[:MAX_OPTIONS]}"
    if fmt(f):
        line += f" | format: {fmt(f)}"
    if guidance:
        line += f" | the applicant's instruction: {guidance}"
    return line


def _parse(reply) -> dict:
    reply = F._THINK.sub("", reply or "")
    i = reply.find("{")
    if i < 0:
        return {}
    try:
        obj, _ = json.JSONDecoder().raw_decode(reply[i:])
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _norm_value(val) -> str:
    val = {True: "Yes", False: "No"}.get(val, val) if isinstance(val, bool) else val
    return {"true": "Yes", "false": "No"}.get(str(val).strip().lower(), str(val if val is not None else "").strip())


def ask_local_packet(llm, packet, job, facts, cards):
    """{ref: (value, card)} from ONE local call for the whole section; ('', 'LOCAL-DOWN: …') for all on a bad reply."""
    keys = []
    for f in packet:
        for c in cards.top(question_of(f.label, f.ref)):
            if c not in keys:
                keys.append(c)
    keys = keys[:MAX_CARDS] + (["today"] if "today" not in keys[:MAX_CARDS] else [])
    lines = "\n".join(f"[{c}] {facts[c]['desc']} ({facts[c]['type']}) = {_show(facts[c]['value'])}" for c in keys if c in facts)
    fields = "\n".join(_field_line(i, f) for i, f in enumerate(packet, 1))
    prompt = (f"{F.applicant_context(job)}\n\n"
              f"You fill the fields of one section of this application — \"{title(packet)}\" — using ONLY the fact cards "
              f"below. Read the fields together: they belong to the same part of the form.\n\nFields:\n{fields}\n\n"
              f"Fact cards:\n{lines}\n\n"
              "Rules: each value must be copied from one card or derived from it by simple reasoning (age from a date, "
              "comparison, unit conversion, a level implying yes/no, a per-company list for this job's company, a "
              "skill missing from the skills grid = 0). A field with options gets exactly one of its options. A "
              "DIFFERENT quantity (alternate number, percentage vs CGPA, IP agreement vs non-compete) is not the same "
              "fact. Yes/no questions answer Yes or No. A field that is not a real question, or that no card settles, "
              "gets NONE.\n"
              'Reply JSON only, one entry per field: {"F1": {"value": "...", "card": "card id used"}, "F2": ...}')
    obj = {}
    for _ in range(2):                                    # one retry: a malformed reply is not a NONE
        try:
            obj = _parse(llm(prompt))
        except Exception:
            obj = {}
        if obj:
            break
    out = {}
    for i, f in enumerate(packet, 1):
        a = obj.get(f"F{i}") if obj else None
        if not obj:
            out[f.ref] = ("", "LOCAL-DOWN: no readable reply")
            continue
        if not isinstance(a, dict):
            out[f.ref] = ("", "")
            continue
        card = str(a.get("card") or "").strip()
        m = re.search(r"\[([^\]]+)\]", card)
        card = m.group(1) if m else (card.split()[0] if card else "")
        out[f.ref] = (_norm_value(a.get("value")), card)
    return out, keys


def plan_packet(llm, packet, job, facts, cache=None, guidance=None):
    """{ref: compiled reply} — cached wordings from the PlanCache, the rest from ONE Haiku call. Raises when Haiku is
    unreachable (the caller fails closed, as the one-field path does)."""
    guidance = guidance or (lambda f: "")
    out, todo = {}, []
    for f in packet:
        key = F.plan_key(question_of(f.label, f.ref), guidance(f))
        hit = cache.get(key) if cache is not None else None
        if hit is not None:
            out[f.ref] = hit
        else:
            todo.append(f)
    if not todo:
        return out
    fields = "\n".join(_field_line(i, f, guidance(f)) for i, f in enumerate(todo, 1))
    prompt = (f"{F.applicant_context(job)}\n\n"
              "You translate the fields of one section of a job-application form — "
              f"\"{title(todo)}\" — into plans over the candidate's stored facts. You see the facts' names and types, "
              "not their values; each plan is executed later. Read the fields together: they belong to the same part "
              f"of the form.\n\nFields:\n{fields}\n\nStored facts:\n{F.schema(facts)}\n\n{F.OPS_HELP}\n\n"
              f"{F.COMPILE_RULES}"
              "For EACH field give one reply of the shapes below, keyed by its id: "
              '{"F1": {"plan": ...}, "F2": {"missing": {...}}, ...}\n' + F.PLAN_SHAPES)
    obj = _parse(llm(prompt))                             # a failed call raises: the caller fails closed
    for i, f in enumerate(todo, 1):
        got = obj.get(f"F{i}")
        got = got if isinstance(got, dict) else {}
        out[f.ref] = got
        if cache is not None and got:                     # an unreadable reply ({}) is not kept
            cache[F.plan_key(question_of(f.label, f.ref), guidance(f))] = got
    return out


def answer_packet(packet, job, facts, cards, *, local_llm, haiku_llm, cache=None, guidance=None):
    """{ref: (value or None, note)} for one section, through the same gate as the one-field path."""
    with ThreadPoolExecutor(1) as pool:                   # the local reader runs while Haiku compiles
        fut = pool.submit(ask_local_packet, local_llm, packet, job, facts, cards) if local_llm else None
        try:                                              # Haiku in THIS thread: the plan cache is sqlite
            plans = plan_packet(haiku_llm, packet, job, facts, cache, guidance)
        except Exception as e:
            if fut:
                fut.cancel()
            return {f.ref: (None, f"haiku unreachable, escalate: {type(e).__name__}") for f in packet}
        local, keys = fut.result() if fut else ({}, [])
    out = {}
    for f in packet:
        q = question_of(f.label, f.ref)
        if F._OPTION_RUN.fullmatch((q or "").strip()):
            out[f.ref] = (None, "unreadable label")
            continue
        value, card = local.get(f.ref, ("", "no local reader"))
        local_val, card = check_local(value, card, q, f.kind, f.options or [], facts, keys) if local_llm else \
            (None, "no local reader")
        plan_val, note = F.evaluate(plans.get(f.ref) or {}, q, f.kind, f.options or [], facts,
                                    f"{f.ref} {getattr(f, 'input_type', '') or ''}")
        out[f.ref] = gate(plan_val, note, local_val, card)
    return out
