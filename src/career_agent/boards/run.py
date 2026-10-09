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
from ..browser.clicks import timeout_ms, wait
from ..browser.form_model import Field
from ..orchestrator.sensitive import split_sensitive
from .drivers import DRIVERS
from .run_log import BoardRunLog
from .profiles import on_board
from ..browser.page_prep import is_login_page
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


def _form_already_open(page) -> bool:
    """An application dialog with fields and an enabled button is already on screen (the entry control sits
    behind it, so clicking it times out). Structural: a visible dialog holding a text field."""
    try:
        return bool(page.evaluate("""() => Array.from(document.querySelectorAll('[role=dialog],[aria-modal=true]')).some(d => {
            const r = d.getBoundingClientRect();
            return r.width > 50 && r.height > 50 && d.querySelector('textarea,input:not([type=hidden]):not([type=checkbox]):not([type=radio]),select,[role=combobox]');
        })"""))
    except Exception:
        return False


def _authorized(ctx, board, page, decisions):
    """The irreversible click: allowed by the dashboard's policy (switch for this site, answers with 3 approvals, a first
    submit there already done by you, daily cap), or by --submit plus a human yes. ctx["how"] records which."""
    policy = ctx.get("autosubmit_policy")
    if policy:
        verdict = policy(page.url, [dataclasses.asdict(d) for d in decisions])
        ctx["eligibility"] = verdict
        if verdict["allow"]:
            ctx["how"] = "auto"
            return True
    if not ctx.get("do_submit"):
        return False
    likely = any(getattr(d, "source", "") == "qbank_likely" for d in decisions)
    if ctx.get("autonomous") and not likely:
        ctx["how"] = "auto"
        return True
    card = [f"Apply via {board['id']}: {page.url[:120]}"]
    if likely:
        card[0] += " (contains best-guess answers — check them)"
    card += [f"- {d.label}: {d.value}" for d in decisions if d.label]
    ok = bool(ctx["human"].approve("\n".join(card)))
    ctx["how"] = "tap"
    return ok


def _interstitials(page, board):
    for sel in board.get("interstitial", []):
        try:
            loc = page.locator(sel).first
            if loc.is_visible():
                loc.click(timeout=timeout_ms(3000))
                wait(page, 1500)
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


def _pair_from_profile(choice, value, ctx):
    """Answer a trailing choice + place from the profile instead of the human:
    willing to relocate -> 'relocate to…' + the job's location; else 'currently
    in…' + the profile city. {} when the profile cannot decide."""
    contact = getattr(ctx.get("profile"), "contact", None) or {}
    reloc = next((o for o in choice.options if "relocat" in o.lower()), None)
    here = next((o for o in choice.options if re.search(r"\b(currently|live|based)\b", o, re.I)), None)
    if contact.get("willing_to_relocate") and reloc and ctx.get("job_location"):
        return {choice.ref: reloc, value.ref: ctx["job_location"]}
    city = (contact.get("location") or "").split(",")[0].strip()
    if here and city:
        return {choice.ref: here, value.ref: city}
    return {}


def _job_location(text):
    """The job's location as the posting states it ('Location' label line)."""
    m = re.search(r"(?im)^\s*location\s*:?\s*\n?\s*([^\n|•]{2,60})$", text or "")
    return m[1].strip() if m else None


def _ask(needs, ctx):
    """Answers for `needs` -> (decisions, still unanswered): the profile first for
    a trailing choice + place, then the human. Probe never asks the human."""
    profile_decisions = []
    choice, value = _paired(needs)
    if choice:
        auto = _pair_from_profile(choice, value, ctx)
        if auto:
            print(f"[board] answered from profile: {auto}", flush=True)
            profile_decisions = [
                FillDecision(choice.ref, choice.kind, choice.label, auto[choice.ref], _action_for_kind(choice.kind), "profile"),
                FillDecision(value.ref, value.kind, value.label, auto[value.ref], "combobox", "profile")]
            needs = [f for f in needs if f not in (choice, value)]
    got, left = _ask_human(needs, ctx)
    return profile_decisions + got, left


def _ask_human(needs, ctx):
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
    record_answers(needs, answers, ctx)
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
    log = BoardRunLog(ctx.get("run_dir"))           # screenshots + steps for the tracker
    assist = ctx.get("assist")                      # opt-in Claude help at dead ends (orchestrator/claude_assist.py)

    def stop(reason, pg):
        res.update(stopped_reason=reason, url=pg.url, submitted=reason == "submitted",
                   decisions=[dataclasses.asdict(d) for d in done_decisions])
        if ctx.get("eligibility"):
            res["eligibility"] = ctx["eligibility"]
        log.finish(pg, reason, res["pending_human"])
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
        from ..browser.clicks import pace
        pace(page)
        _before = list(page.context.pages)
        try:
            page.locator(board["entry"]["selector"]).filter(visible=True).first.click(timeout=timeout_ms(15000), no_wait_after=True)
        except Exception as e:
            if _form_already_open(page):
                ctx["baseline"] = set()           # an earlier run left the form open: every field on it is the form's
            elif not (assist and assist.recover(page, "no_entry")):     # a recovery click replaces the entry click
                res["error"] = f"{type(e).__name__}: {str(e)[:300]}"
                return stop("no_entry", page)
        wait(page, 3000)
        from ..browser.page_prep import new_tab_since
        page = new_tab_since(page, _before)      # the entry click may open a new tab
        _interstitials(page, board)
        try:
            title = page.title().split("|")[0].strip()
        except Exception:
            title = ""
        ctx["ask_context"] = f"{board.get('label', board['id'])} — {title}" if title else board.get("label")
        try:
            ctx["job_location"] = _job_location(page.evaluate("document.body.innerText"))
        except Exception:
            ctx["job_location"] = None

        asked_optional = False
        unanswered = 0
        for _ in range(MAX_STEPS):
            if confirmed(board, cap.responses, page.url):
                break
            from ..browser.clicks import wait_until_stable
            wait_until_stable(page)                   # the step may still be drawing after the URL changed
            blocked = _blocked(page, board)
            if blocked:
                return stop(blocked, page)
            if not on_board(page.url, board):
                return stop("left_board", page)     # e.g. "Apply on company site": another engine takes over
            if is_login_page(page):
                return stop("auth_wall", page)      # a login/sign-up wall is never a question for a human
            ctx["page_index"] = log.page(page)
            fields, blocked = split_sensitive(driver.fields(page, board, ctx, cap))
            if any(f.required for f in blocked):          # bank / ID details: yours to fill, never asked
                res["pending_human"] = [dataclasses.asdict(f) for f in blocked if f.required]
                return stop("sensitive_field", page)
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
            log.filled(page)                              # screenshot of the filled page, before Next
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
                    log.filled(page)
                    wait(page, 1500)
                    continue
            if nxt is None:
                if assist and assist.recover(page, "no_advance_control"):
                    continue
                break
            label, final = nxt
            if final:
                if not _authorized(ctx, board, page, done_decisions):
                    return stop("dry_run", page)
                irreversible = True
                try:
                    from ..browser.form_values import read_form_values
                    before_submit = read_form_values(page)             # what the form holds as it goes out
                except Exception:
                    before_submit = {}
            from ..browser.clicks import page_signature, wait_for_change
            before_click = page_signature(page)
            driver.click(page, label, ctx)
            wait(page, 2500)
            if page_signature(page) == before_click and not wait_for_change(page, before_click):
                # The page has not answered the click. Clicking again is how a step gets skipped (the second click
                # lands on the page that was merely slow): allow one more wait-and-retry, then stop as stuck.
                unanswered += 1
                if unanswered >= 2:
                    return stop("stuck", page)
            else:
                unanswered = 0
        wait(page, 1500)
        ok = confirmed(board, cap.responses, page.url)
    if ok and irreversible and ctx.get("on_submit"):
        try:
            ctx["on_submit"](before_submit if "before_submit" in locals() else {}, ctx.get("how", "tap"), page.url)
        except Exception:
            pass
    return stop("submitted" if ok else "unconfirmed" if irreversible else "stuck", page)
