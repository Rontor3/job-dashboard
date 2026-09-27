"""Board pipeline: blocked? → entry → questions → shared answer ladder → human
for required gaps → put → advance → gated irreversible click → confirm from the
board's own response. Never creates accounts, never uses the career-site drill,
stops on bot challenges. Result dict matches the career-site one (+ `board`)."""
from __future__ import annotations

import dataclasses
import re

from job_dashboard.sources.cdp.session import Capture

from ..orchestrator.answering import answer_fields, record_answers
from ..orchestrator.mapper import FillDecision, _action_for_kind
from ..orchestrator.screen_review import apply_answers
from ..browser.form_model import Field
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
    # Frame URLs too: a Cloudflare interstitial renders its widget in a
    # challenges.cloudflare.com frame over an otherwise ordinary-looking URL.
    frames = " ".join(f.url for f in getattr(page, "frames", []) or [])
    if is_challenge(board, f"{page.url} {frames}", text):
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


_REF_NOISE = {"react", "select", "form", "input", "field", "data", "cref", "id", "qualification",
              "group", "button", "the", "value"}


def _readable(f):
    """A field as the human should see it: unlabelled widgets (a react-select
    location picker) get a name derived from their ref instead of raw CSS."""
    if f.label and f.label.strip():
        label = f.label.strip()
        if f.options and not label.endswith("?"):
            # A statement heading a choice ("This job does not support the
            # locations on your profile.") reads as a question to the human.
            label = f"{label} Which applies to you?"
        return dataclasses.replace(f, label=label)
    words = []
    for tok in re.findall(r"[A-Za-z]+", f.ref or ""):
        for w in re.findall(r"[A-Z]?[a-z]+", tok):
            w = w.lower()
            if w not in _REF_NOISE and w not in words:
                words.append(w)
    return dataclasses.replace(f, label=" ".join(words).capitalize() or "Unlabelled field")


def _paired(needs):
    """(choice, value): a choice whose options trail off ("I can relocate to…")
    next to an unlabelled value field — one question for the human, not two."""
    choice = next((f for f in needs if f.options
                   and all(o.rstrip().endswith(("…", "...")) for o in f.options)), None)
    value = next((f for f in needs if f.kind in ("text", "combobox")
                  and not (f.label or "").strip()), None)
    return (choice, value) if choice and value else (None, None)


def _ask_pair(human, choice, value):
    opts = "\n".join(f"  {i + 1}) {o}" for i, o in enumerate(choice.options))
    q = Field("pair:" + choice.ref, "text",
              f"{choice.label.strip()}\n{opts}\nReply with the number and the place, e.g. \"2 New Delhi\"",
              True, [], None, None)
    reply = str((human.collect([q]) or {}).get(q.ref) or "")
    print(f"[board] asked (paired) {choice.label[:60]!r} -> reply {reply!r}", flush=True)
    m = re.match(r"\s*(\d+)\s*[.,:)-]?\s*(.*)", reply)
    if not m or not 1 <= int(m[1]) <= len(choice.options):
        return {}
    opt, place = choice.options[int(m[1]) - 1], m[2].strip()
    if not place:                               # "2" alone: ask for the place it trails off to
        q2 = Field("pair2:" + value.ref, "text", f"{opt.rstrip('….').strip()} — which place?",
                   True, [], None, None)
        place = str((human.collect([q2]) or {}).get(q2.ref) or "").strip()
        print(f"[board] asked follow-up -> reply {place!r}", flush=True)
    return {choice.ref: opt, **({value.ref: place} if place else {})}


def _ask(needs, ctx):
    """Human answers for `needs` -> (decisions, still unanswered). Probe never asks."""
    if not needs or ctx.get("probe"):
        return [], needs
    human = ctx["human"]
    collector = getattr(human, "collector", None)
    if collector is not None and ctx.get("ask_context") and hasattr(collector, "context"):
        collector.context = ctx["ask_context"]       # "Wellfound — AI Engineer at VisionSure"
    try:
        answers = {}
        choice, value = _paired(needs)
        if choice:
            answers.update(_ask_pair(human, choice, value))
        rest = [f for f in needs if f not in (choice, value)]
        if rest:
            print(f"[board] asking: {[_readable(f).label[:50] for f in rest]}", flush=True)
            answers.update(human.collect([_readable(f) for f in rest]) or {})
        print(f"[board] human answers: {answers}", flush=True)
    except Exception as e:                 # no terminal / Telegram down: leave the gap open
        print(f"[board] could not ask the human ({type(e).__name__}); leaving {len(needs)} field(s) open", flush=True)
        answers = {}
    record_answers(needs, answers, ctx, human.get_events() or {})
    return apply_answers(needs, answers), [f for f in needs if not str(answers.get(f.ref) or "").strip()]


def _answers(fields, board, driver, cap, ctx):
    """(decisions, unanswered required, unanswered optional): ladder -> board
    prefill -> human for required gaps (all gaps when the driver asks upfront)."""
    decisions, _ = answer_fields(fields, ctx)
    pre = driver.prefill(board, cap)
    decided = {d.ref for d in decisions}
    decisions += [FillDecision(f.ref, f.kind, f.label, pre[f.ref], _action_for_kind(f.kind), "board_prefill")
                  for f in fields if f.ref in pre and f.ref not in decided]
    # A gap is any field the ladder gave no answer for — including optional
    # radios/selects the rules layer passes over silently.
    decided |= set(pre)
    gaps = [f for f in fields if f.ref not in decided]
    upfront = gaps if driver.ask_optional_upfront else [f for f in gaps if f.required]
    got, left = _ask(upfront, ctx)
    return (decisions + got, [f for f in left if f.required],
            [f for f in gaps if not f.required and f not in upfront] + [f for f in left if not f.required])


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
        if irreversible and ctx.get("probe"):
            # Probe never clicks an entry that itself submits: just prove it is there.
            try:
                found = page.locator(board["entry"]["selector"]).first.is_visible()
            except Exception:
                found = False
            return stop("probe" if found else "no_entry", page)
        if irreversible and not _authorized(ctx, board, page, []):
            return stop("dry_run", page)
        try:
            page.locator(board["entry"]["selector"]).filter(visible=True).first.click(timeout=15000)
        except Exception as e:
            res["error"] = f"{type(e).__name__}: {str(e)[:300]}"
            return stop("no_entry", page)
        page.wait_for_timeout(3000)
        page = page.context.pages[-1]            # the entry click may open a new tab
        _interstitials(page, board)
        try:
            title = page.title().split("|")[0].strip()
        except Exception:
            title = ""
        ctx["ask_context"] = f"{board.get('label', board['id'])} — {title}" if title else board.get("label")

        asked_optional = False
        for _ in range(MAX_STEPS):
            if confirmed(board, cap.responses, page.url):
                break
            blocked = _blocked(page, board)
            if blocked:
                return stop(blocked, page)
            fields = driver.fields(page, board, ctx, cap)
            decisions, needs, optional = _answers(fields, board, driver, cap, ctx)
            if ctx.get("probe"):
                # Probe: report what would be filled / asked on the first form
                # page, then stop — nothing typed, nothing submitted.
                done_decisions += decisions
                res["pending_human"] = [dataclasses.asdict(f) for f in needs + optional]
                res["fields"] = [dataclasses.asdict(f) for f in fields]
                return stop("probe", page)
            if needs:
                res["pending_human"] = [dataclasses.asdict(f) for f in needs]
                return stop("needs_human", page)
            driver.put(page, board, ctx, fields, decisions)
            done_decisions += decisions
            nxt = driver.next_control(page, board, ctx)
            if nxt is None and optional and not asked_optional:
                # The form will not advance (Next/Submit absent or disabled) while
                # "optional" fields are blank: one of them is required in practice
                # (e.g. Wellfound's location question gates Send). Ask, then re-read.
                asked_optional = True
                got, _ = _ask(optional, ctx)
                if got:
                    driver.put(page, board, ctx, fields, got)
                    done_decisions += got
                    page.wait_for_timeout(1500)
                    continue
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
