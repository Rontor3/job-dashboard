"""The shared answer ladder — question bank → profile rules → LLM judge — used by
the career-site graph (fill_node / human_gate_node) and the board pipeline.
`ctx` is a plain dict (the graph's `configurable`): learn (QBankMemory), profile,
resume_pdf, judge_fn, qa (QARecorder, optional). Never touches the page."""
from __future__ import annotations

import re
from dataclasses import replace


_MONEY_FIELD = re.compile(r"salary|compensation|\bctc\b|\bpay\b|remuneration", re.I)
_AMOUNT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(lpa|lakhs?|lacs?|l)?\s*$", re.I)
_LAKH_HINT = re.compile(r"lpa|lakh|lac\b|lacs", re.I)
_ABSOLUTE_HINT = re.compile(r"\binr\b|₹|rupee|\brs\b|digits?|local currency|absolute|exact amount", re.I)


def normalize_amount(value, label: str, input_type: str = "", absolute: bool = False):
    """Write a CTC the way the box wants it. Stored values are in lakhs ('25', '35 LPA'); a bare number under 1000
    is lakhs. A label asking for LPA/lakhs gets the plain lakh number, one asking for INR / digits / local currency
    (or a number input) gets rupees, 'per month' gets a twelfth; an unmarked text box gets '25 LPA' so it is unambiguous."""
    m = _AMOUNT.match(str(value))
    if not m or not _MONEY_FIELD.search(label or ""):
        return value
    num, unit = float(m.group(1)), m.group(2)
    if unit is None and num >= 1000:
        return value                                        # already an absolute amount
    plain = lambda x: str(int(x)) if float(x).is_integer() else str(round(x, 2))
    monthly = bool(re.search(r"month", label or "", re.I))
    if _LAKH_HINT.search(label or ""):
        return plain(num / 12 if monthly else num)
    if monthly or absolute or _ABSOLUTE_HINT.search(label or "") or input_type == "number":
        rupees = num * 100000
        return str(round(rupees / 12 if monthly else rupees))
    return value if unit else f"{plain(num)} LPA"


_DIAL_FIELD = re.compile(r"country.{0,12}code|dial(l?ing)?\s*code|calling\s*code|phone\s*(code|prefix)|countrycode", re.I)
_DIAL_OPTION = re.compile(r"^\s*\+\d{1,3}\b|\(\+\d{1,3}\)")
_LEADING_DIAL = re.compile(r"^\s*\+\d{1,3}[\s\-.]*(?=\d)")


_CURRENCY = re.compile(r"currency", re.I)
_CURRENCY_OPTIONS = {"inr", "usd", "eur", "gbp", "aed", "sgd", "₹", "$"}


def has_currency_field(fields) -> bool:
    """The form picks the currency in a field of its own (by label/ref, or a select offering INR/USD/...)."""
    return any(_CURRENCY.search(f"{f.label or ''} {f.ref or ''}") or
               len({o.strip().lower() for o in (f.options or [])} & _CURRENCY_OPTIONS) >= 2 for f in fields)


def has_dial_field(fields) -> bool:
    """The form asks for the country code in a field of its own (by label/ref, or a select whose options are +NN)."""
    return any(_DIAL_FIELD.search(f"{f.label or ''} {f.ref or ''}") or
               sum(bool(_DIAL_OPTION.search(o)) for o in (f.options or [])) >= 3 for f in fields)


_PHONE_LABEL = re.compile(r"phone|mobile|whats ?app|contact (no|number)|\btel\b", re.I)


def _is_phone(field) -> bool:
    return getattr(field, "input_type", "") == "tel" or bool(_PHONE_LABEL.search(field.label or ""))


def national_number(value, field, dial_field: bool):
    """With a separate country-code field, the phone box takes the number alone: '+91 7565052330' -> '7565052330'
    (live Keka form, 2026-10-12, got the +91 twice). The dial-code field itself is left as it is."""
    if not dial_field or _DIAL_FIELD.search(f"{field.label or ''} {field.ref or ''}"):
        return value
    return _LEADING_DIAL.sub("", value) if isinstance(value, str) else value
_FIRST_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def shape_value(value, label: str, input_type: str = "", unit: str = "", absolute: bool = False):
    """Fit an answer to the box it goes in. The box's unit (a currency/"Years" control sharing its row) counts as part
    of its label for amounts; a number-only box (<input type=number>) takes the number alone — "30 days" -> "30",
    which it would otherwise reject and leave blank. `absolute`: the form has its own currency field, so a salary is
    an amount ("25 LPA" -> "2500000")."""
    value = normalize_amount(value, f"{label or ''} {unit or ''}".strip(), input_type, absolute=absolute)
    if input_type == "number":
        m = _FIRST_NUMBER.search(str(value).replace(",", ""))
        return m.group(0) if m else value
    return value


def _prior_human_answers(fields, qa) -> list:
    """What the human already answered for this same application (an earlier run asked, they replied): used as-is,
    so a re-run does not ask again. Checkboxes: only a 'yes' is acted on."""
    if not qa or getattr(qa, "job_id", None) is None:
        return []
    try:
        from job_dashboard import qa_store
        prior = qa_store.prior_answers(qa.conn, qa.job_id, getattr(qa, "run_key", None))
    except Exception:
        return []
    from .mapper import FillDecision, _action_for_kind
    out = []
    for f in fields:
        a = prior.get(qa_store.norm_key(f.label)) if f.kind not in ("file", "button") else None
        if not a:
            continue
        if f.kind == "checkbox":
            if str(a).strip().lower() not in ("yes", "true", "1", "checked", "y"):
                continue
            out.append(FillDecision(f.ref, f.kind, f.label, True, "check", "human_prior"))
        else:
            out.append(FillDecision(f.ref, f.kind, f.label, a, _action_for_kind(f.kind), "human_prior"))
    return out


_OTHER_FOLLOWUP = re.compile(r"\b(if|in case)\b[^?.]{0,80}\bother\b|\bother\b[^?.]{0,40}\bplease (specify|state|describe)\b", re.I)


def _drop_other_followups(fields, decisions, needs):
    """"In case you selected Other, specify your start date here": a box that belongs to an "Other" option. Filled only when
    some answer chose Other; otherwise it stays blank and is not asked."""
    follow = {f.ref for f in fields if f.kind in ("text", "textarea") and _OTHER_FOLLOWUP.search(f.label or "")}
    if not follow or any(re.match(r"\s*other\b", str(d.value), re.I) for d in decisions if d.ref not in follow):
        return decisions, needs
    return [d for d in decisions if d.ref not in follow], [f for f in needs if f.ref not in follow]


def answer_fields(fields, ctx):
    """(decisions, needs) for `fields`: decline gate, question bank (confident + likely), profile
    rules, then the LLM judge. Every field is recorded to ctx['qa'] when present,
    so likely fills and gaps surface for review on every path (graph and boards).
    The decline gate (decline_class) answers marketing opt-ins itself and holds
    their required variants back from every ask tier — before the screen-review
    tier and before judge() ever sees a question."""
    qa = ctx.get("qa")
    learn = ctx.get("learn")
    if learn is not None and hasattr(learn, "prime"):
        try:
            learn.prime(fields)                    # section by section, before the per-field path (memory/sections.py)
        except Exception as e:
            print(f"[warn] section answering failed, falling back to one field at a time: {type(e).__name__}: {e}")
    if qa:
        if ctx.get("page_index") is not None:
            qa.page = ctx["page_index"]            # the tracker groups questions by form page
        qa.trace_all(fields)
    recalled, remaining = _prior_human_answers(fields, qa), list(fields)
    done = {d.ref for d in recalled}
    remaining = [f for f in remaining if f.ref not in done]
    # The gate runs first (its declines never become questions/bank work):
    # what it claims is neither filled by a tier nor asked. Optional marketing
    # gets an affirmative declining decision; a REQUIRED marketing ask is held
    # undecided — no "No" is ever stuffed into it (qbank_memory's invariant) —
    # and is re-added to `needs` below so the human decides it at the
    # escalation boundary, with the hold recorded to application_qa.
    from .decline_class import gate as decline_gate
    declined, remaining, held = decline_gate(remaining)
    learn = ctx.get("learn")
    if learn:
        more, remaining = learn.recall(remaining)
        recalled += more                          # never instead of: the human's own answers were taken out above
    from .screen_review import map_screen
    decisions, needs = map_screen(remaining, ctx["profile"], ctx.get("resume_pdf"))
    decisions = declined + recalled + decisions
    judge_fn = ctx.get("judge_fn")
    if needs and judge_fn:
        answered, needs, _ = judge_fn(needs)
        decisions += answered
    needs += [f for f, _, escalated in held if escalated]     # judge() has already run: these were never its questions
    itype = {f.ref: getattr(f, "input_type", "") or "" for f in fields}
    # a form with its own currency field wants the salary as an amount (Keka: Current Salary + INR select got "25 LPA")
    cur = has_currency_field(fields)
    unit = {f.ref: getattr(f, "unit", "") or "" for f in fields}
    decisions = [replace(d, value=shape_value(d.value, d.label, itype.get(d.ref, ""), unit.get(d.ref, ""), absolute=cur))
                 if d.action == "fill" and d.value is not None else d for d in decisions]
    # A city box takes the city alone: a stored "Mumbai, India" (qbank current_city) gives "Mumbai".
    purpose = {f.ref: f.purpose for f in fields}
    decisions = [replace(d, value=d.value.split(",")[0].strip())
                 if d.action == "fill" and purpose.get(d.ref) == "city" and isinstance(d.value, str) else d
                 for d in decisions]
    dial, by_ref = has_dial_field(fields), {f.ref: f for f in fields}
    decisions = [replace(d, value=national_number(d.value, by_ref[d.ref], dial))
                 if d.action == "fill" and d.ref in by_ref and _is_phone(by_ref[d.ref]) else d for d in decisions]
    decisions, needs = _drop_other_followups(fields, decisions, needs)
    if qa:
        for f, basis, _ in held:          # the gate's hold-backs, auditable even when nothing else touches them
            qa.held(f, basis)
        for d in decisions:
            qa.decision(d)
        for f in needs:
            qa.needs(f)                   # a required hold-back flips its earlier held row to needs_answer (source stays decline_class)
    return decisions, needs


def record_answers(fields, answers, ctx):
    """Human answers are kept per application (application_qa) only; they join the
    question bank when promoted on the dashboard (spec 2026-09-26 §3)."""
    qa = ctx.get("qa")
    if not qa:
        return
    for f in fields:
        ans = answers.get(f.ref)
        if ans is not None and str(ans).strip():
            qa.answered(f, str(ans).strip())
