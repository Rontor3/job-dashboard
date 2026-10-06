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


def normalize_amount(value, label: str, input_type: str = ""):
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
    if monthly or _ABSOLUTE_HINT.search(label or "") or input_type == "number":
        rupees = num * 100000
        return str(round(rupees / 12 if monthly else rupees))
    return value if unit else f"{plain(num)} LPA"


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


def answer_fields(fields, ctx):
    """(decisions, needs) for `fields`: question bank (confident + likely), profile
    rules, then the LLM judge. Every field is recorded to ctx['qa'] when present,
    so likely fills and gaps surface for review on every path (graph and boards)."""
    qa = ctx.get("qa")
    if qa:
        if ctx.get("page_index") is not None:
            qa.page = ctx["page_index"]            # the tracker groups questions by form page
        qa.trace_all(fields)
    recalled, remaining = _prior_human_answers(fields, qa), list(fields)
    done = {d.ref for d in recalled}
    remaining = [f for f in remaining if f.ref not in done]
    learn = ctx.get("learn")
    if learn:
        recalled, remaining = learn.recall(remaining)
    from .screen_review import map_screen
    decisions, needs = map_screen(remaining, ctx["profile"], ctx.get("resume_pdf"))
    decisions += recalled
    judge_fn = ctx.get("judge_fn")
    if needs and judge_fn:
        answered, needs, _ = judge_fn(needs)
        decisions += answered
    itype = {f.ref: getattr(f, "input_type", "") or "" for f in fields}
    decisions = [replace(d, value=normalize_amount(d.value, d.label, itype.get(d.ref, "")))
                 if d.action == "fill" and d.value is not None else d for d in decisions]
    if qa:
        for d in decisions:
            qa.decision(d)
        for f in needs:
            qa.needs(f)
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
