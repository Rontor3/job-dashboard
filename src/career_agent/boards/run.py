"""Board pipeline: blocked? → entry → questions → shared answer ladder → human
for required gaps → put → advance → gated irreversible click → confirm from the
board's own response. Never creates accounts, never uses the career-site drill,
stops on bot challenges. Result dict matches the career-site one (+ `board`)."""
from __future__ import annotations

import dataclasses

from job_dashboard.sources.cdp.session import Capture

from ..orchestrator.answering import answer_fields, record_answers
from ..orchestrator.mapper import FillDecision, _action_for_kind
from ..orchestrator.screen_review import apply_answers
from .drivers import DRIVERS
from .signals import confirmed, is_challenge, is_logged_out

MAX_STEPS = 8


def _needles(board):
    rules = list(board.get("confirm", [])) + [board.get("questions") or {}]
    return tuple(r["capture"] for r in rules if r.get("capture"))


def _blocked(page, board):
    try:
        text = page.evaluate("document.body ? document.body.innerText.slice(0, 4000) : ''")
    except Exception:
        text = ""
    if is_challenge(board, page.url, text):
        return "challenge"
    if is_logged_out(board, page.url, text):
        return "logged_out"
    return None


def _authorized(ctx, board, page, decisions):
    """The irreversible click needs --submit AND (standing authorization or a human yes)."""
    if not ctx.get("do_submit"):
        return False
    if ctx.get("autonomous"):
        return True
    card = [f"Apply via {board['id']}: {page.url[:120]}"]
    card += [f"- {d.label}: {d.value}" for d in decisions if d.label]
    return bool(ctx["human"].approve("\n".join(card)))


def _interstitials(page, board):
    for sel in board.get("interstitial", []):
        try:
            loc = page.locator(sel).first
            if loc.is_visible():
                loc.click(timeout=3000)
                page.wait_for_timeout(1500)
        except Exception:
            pass


def _answers(fields, board, driver, cap, ctx):
    """(decisions, unanswered required fields): ladder → board prefill → human."""
    decisions, needs = answer_fields(fields, ctx)
    pre = driver.prefill(board, cap)
    decisions += [FillDecision(f.ref, f.kind, f.label, pre[f.ref], _action_for_kind(f.kind), "board_prefill")
                  for f in needs if f.ref in pre]
    needs = [f for f in needs if f.ref not in pre and f.required]
    if needs:
        human = ctx["human"]
        answers = human.collect(needs) or {}
        record_answers(needs, answers, ctx, human.get_events() or {})
        decisions += apply_answers(needs, answers)
        needs = [f for f in needs if not str(answers.get(f.ref) or "").strip()]
    return decisions, needs


def run_board(page, board, ctx):
    ctx = dict(ctx)
    res = {"url": page.url, "job_id": ctx.get("job_id"), "board": board["id"], "submitted": False,
           "stopped_reason": None, "decisions": [], "pending_human": []}
    done_decisions = []

    def stop(reason, pg):
        res.update(stopped_reason=reason, url=pg.url, submitted=reason == "submitted",
                   decisions=[dataclasses.asdict(d) for d in done_decisions])
        return res

    blocked = _blocked(page, board)
    if blocked:
        return stop(blocked, page)
    driver = DRIVERS[board["archetype"]]
    ctx["baseline"] = {(f.label, f.kind) for f in ctx["deps"].snapshot(page)}
    irreversible = board["entry"].get("submits", "no") != "no"

    with Capture(page.context, _needles(board)) as cap:
        if irreversible and not _authorized(ctx, board, page, []):
            return stop("dry_run", page)
        try:
            page.locator(board["entry"]["selector"]).first.click(timeout=8000)
        except Exception:
            return stop("no_entry", page)
        page.wait_for_timeout(3000)
        page = page.context.pages[-1]            # the entry click may open a new tab
        _interstitials(page, board)

        for _ in range(MAX_STEPS):
            if confirmed(board, cap.responses, page.url):
                break
            blocked = _blocked(page, board)
            if blocked:
                return stop(blocked, page)
            fields = driver.fields(page, board, ctx, cap)
            decisions, needs = _answers(fields, board, driver, cap, ctx)
            if needs:
                res["pending_human"] = [dataclasses.asdict(f) for f in needs]
                return stop("needs_human", page)
            driver.put(page, board, ctx, fields, decisions)
            done_decisions += decisions
            nxt = driver.next_control(page, board, ctx)
            if nxt is None:
                break
            label, final = nxt
            if final:
                if not _authorized(ctx, board, page, done_decisions):
                    return stop("dry_run", page)
                irreversible = True
            driver.click(page, label, ctx)
            page.wait_for_timeout(2500)
        page.wait_for_timeout(1500)
        ok = confirmed(board, cap.responses, page.url)
    return stop("submitted" if ok else "unconfirmed" if irreversible else "stuck", page)
