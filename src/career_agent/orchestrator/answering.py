"""The shared answer ladder — question bank → profile rules → LLM judge — used by
the career-site graph (fill_node / human_gate_node) and the board pipeline.
`ctx` is a plain dict (the graph's `configurable`): learn (QBankMemory), profile,
resume_pdf, judge_fn, qa (QARecorder, optional). Never touches the page."""
from __future__ import annotations


def answer_fields(fields, ctx):
    """(decisions, needs) for `fields`: question bank (confident + likely), profile
    rules, then the LLM judge. Every field is recorded to ctx['qa'] when present,
    so likely fills and gaps surface for review on every path (graph and boards)."""
    qa = ctx.get("qa")
    if qa:
        if ctx.get("page_index") is not None:
            qa.page = ctx["page_index"]            # the tracker groups questions by form page
        qa.trace_all(fields)
    recalled, remaining = [], list(fields)
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
