"""The shared answer ladder — recall → semantic → rules → judge — used by the
career-site graph (fill_node / human_gate_node) and the board pipeline.
`ctx` is a plain dict (the graph's `configurable`): learn, memory_router,
profile, resume_pdf, judge_fn. Never touches the page."""
from __future__ import annotations


def semantic_split(fields, mem_router):
    """(auto_decisions, remaining): semantic-vault answers with confidence >= 1.0
    (3 human approvals) skip the human; everything else falls through."""
    if not mem_router:
        return [], list(fields)
    from .mapper import FillDecision
    auto, rest = [], []
    for f in fields:
        if f.kind not in ("text", "textarea"):
            rest.append(f)
            continue
        hit = mem_router.dispatch("SEMANTIC_MATCH", {"question": f.label or ""})
        if hit and hit.get("autonomous"):
            auto.append(FillDecision(f.ref, f.kind, f.label,
                                     hit["answer"], "semantic", "behavioral"))
        else:
            rest.append(f)
    return auto, rest


def answer_fields(fields, ctx):
    """(decisions, needs) for `fields`: learned recall, autonomous semantic
    answers, profile rules, then the LLM judge for what is left."""
    recalled, remaining = [], list(fields)
    learn = ctx.get("learn")
    if learn:
        recalled, remaining = learn.recall(remaining)
    auto, remaining = semantic_split(remaining, ctx.get("memory_router"))
    from .screen_review import map_screen
    decisions, needs = map_screen(remaining, ctx["profile"], ctx.get("resume_pdf"))
    decisions += recalled + auto
    judge_fn = ctx.get("judge_fn")
    if needs and judge_fn:
        answered, needs, _ = judge_fn(needs)
        decisions += answered
    return decisions, needs


def record_answers(fields, answers, ctx, events=None):
    """Write human answers back so they are recalled next time: semantic vault +
    FTS5 via the memory router when present, else learned_answers."""
    mem_router, learn, events = ctx.get("memory_router"), ctx.get("learn"), events or {}
    for f in fields:
        ans = answers.get(f.ref)
        if ans is None or not str(ans).strip():
            continue
        if mem_router:
            mem_router.dispatch("RECORD_FEEDBACK", {
                "question": f.label or f.ref,
                "answer": str(ans).strip(),
                "event": events.get(f.ref, "approve"),
                "purpose": f.purpose,
            })
        elif learn:
            learn.record(f, ans)
