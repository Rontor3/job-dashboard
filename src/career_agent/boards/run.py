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
from .. import run_trace
from ..orchestrator.screen_review import apply_answers
from ..browser.form_model import Field
from ..orchestrator.sensitive import split_sensitive
from .drivers import DRIVERS
from .run_log import BoardRunLog
from .profiles import on_board
from ..browser.page_prep import is_closed_posting, is_wall, clear_auth_wall, new_tab_since
from .signals import confirmed, is_challenge, is_logged_out

MAX_STEPS = 8


def _needles(board):
    rules = list(board.get("confirm", [])) + [board.get("questions") or {}]
    return tuple(r["capture"] for r in rules if r.get("capture"))


_APPLIED = re.compile(r"\byou(?:'ve| have)? already applied\b|\bapplied \d+ (?:second|minute|hour|day|week|month)s? ago\b",
                      re.I)
# A visible BUTTON reading just "Applied" ("✓ Applied"): nav links named
# "Applied" (Wellfound's sidebar) are anchors, so only buttons count.
_APPLIED_BUTTON_JS = """() => [...document.querySelectorAll('button')].some(e =>
    e.checkVisibility() && /^\\W*applied\\W*$/i.test((e.innerText || '').trim()))"""
_ERRORS_JS = """() => [...new Set([...document.querySelectorAll(
    '[role=alert],[aria-live=assertive],[id*=error i],[class*=error i],[class*=invalid i]')]
    .filter(e => e.checkVisibility() && e.innerText && e.innerText.trim().length < 300)
    .map(e => e.innerText.trim()))].slice(0, 6)"""


def _visible_errors(page):
    try:
        return page.evaluate(_ERRORS_JS)
    except Exception:
        return []


def _posting_state(page, text):
    """'closed' / 'already_applied' when the posting says so before we start."""
    if is_closed_posting(page):
        return "closed"
    try:
        if _APPLIED.search(text or "") or page.evaluate(_APPLIED_BUTTON_JS):
            return "already_applied"
    except Exception:
        pass
    return None


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
    """The application form is already on screen (the entry control sits behind it, or there is none because we
    arrived mid-way through a multi-step form). Structural: a visible dialog holding a field, or two or more
    visible form fields on the page itself (search boxes and hidden/captcha inputs do not count)."""
    try:
        return bool(page.evaluate("""() => {
          const vis = e => { const r = e.getBoundingClientRect(); return r.width > 4 && r.height > 4; };
          const field = e => e.matches('textarea,select,[role=combobox],input:not([type=hidden]):not([type=checkbox]):not([type=submit]):not([type=button]):not([type=search])')
                             && !/search|recaptcha/i.test((e.getAttribute('aria-label') || '') + (e.name || '') + (e.id || ''));
          const dlg = Array.from(document.querySelectorAll('[role=dialog],[aria-modal=true]')).some(d => vis(d) && Array.from(d.querySelectorAll('*')).some(e => field(e) && vis(e)));
          const names = new Set(Array.from(document.querySelectorAll('textarea,select,[role=combobox],input')).filter(e => field(e) && vis(e)).map(e => e.name || e.id || Math.random()));
          // a page still offering an Apply control is the posting, not the form (header search/location boxes count as fields)
          const applyOffered = Array.from(document.querySelectorAll('button,a,[role=button]')).some(e => vis(e)
            && /^(easy )?apply\\b/i.test(((e.innerText || '').trim() || e.getAttribute('aria-label') || '').trim()));
          return dlg || (names.size >= 2 && !applyOffered);
        }"""))
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


def _untick(page, board):
    """Before the final click, untick pre-ticked optional opt-ins (LinkedIn's "Follow <company> to stay up to date",
    Indeed's job-alert emails): applying is not consent to follow or to be mailed. Any checked, non-required box whose
    label reads as an opt-in (screen_review._MARKETING) goes, plus any pattern the board profile lists."""
    from ..orchestrator.screen_review import _MARKETING
    pats = [re.compile(p, re.I) for p in board.get("uncheck", [])] + [_MARKETING]
    try:
        boxes = page.locator("input[type=checkbox]:checked:not([required]):not([aria-required=true])")
        for i in reversed(range(boxes.count())):
            b = boxes.nth(i)
            label = b.evaluate("e => ((e.labels && e.labels[0] ? e.labels[0].innerText : '') || e.getAttribute('aria-label') || '').trim()")
            if label and any(p.search(label) for p in pats):
                b.uncheck(timeout=5000, force=True)
                print(f"[board] unticked optional box {label[:60]!r}", flush=True)
    except Exception:
        pass


def _interstitials(page, board):
    for sel in board.get("interstitial", []):
        try:
            loc = page.locator(sel).first
            if loc.is_visible():
                loc.click(timeout=3000)
                page.wait_for_timeout(1500)
        except Exception:
            pass


def _entry_legs(board):
    """The board's ordered entry legs: the graph node's declared `chain` when it
    has one (an external handoff leg is expected to leave the board), else the
    legacy single selector as the chain's only leg — boards without a chain
    behave exactly as they did."""
    return board["entry"].get("chain") or [{"selector": board["entry"]["selector"]}]


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


def _affirm(fields):
    """Declarations ("I hereby declare… true") the board insists on: pick the
    affirmative option. The authorized submit is the consent point."""
    from ..orchestrator.screen_review import _coerce_option
    out = []
    for f in fields:
        if f.purpose == "attestation":
            opt = _coerce_option("Yes", f.options) if f.options else True
            if opt is not None:
                act = _action_for_kind(f.kind) if f.options else "check"
                out.append(FillDecision(f.ref, f.kind, f.label, opt, act, "attestation"))
    return out


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
    run_trace.start("ask", asked=len(needs))         # the human question round is the slow step worth tracing
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
    run_trace.end("ask", "done", given=len(answers), asked=len(needs))
    record_answers(needs, answers, ctx)
    return apply_answers(needs, answers), [f for f in needs if not str(answers.get(f.ref) or "").strip()]


def _answers(fields, board, driver, cap, ctx):
    """(decisions, unanswered required, unanswered optional): ladder -> board
    prefill -> human for required gaps (all gaps when the driver asks upfront)."""
    decisions, _ = answer_fields(fields, ctx)
    pre = driver.prefill(board, cap)
    decided = {d.ref for d in decisions if d.value is not None}     # a flag is not an answer
    decisions += [FillDecision(f.ref, f.kind, f.label, pre[f.ref], _action_for_kind(f.kind), "board_prefill")
                  for f in fields if f.ref in pre and f.ref not in decided]
    # A gap is any field the ladder gave no answer for — including optional
    # radios/selects the rules layer passes over silently.
    decided |= set(pre)
    gaps = [f for f in fields if f.ref not in decided]
    upfront = gaps if driver.ask_optional_upfront else [f for f in gaps if f.required]
    if upfront and ctx.get("fill_first") and decisions:
        ctx["fill_first"](decisions)        # what is already answered goes in before the human is asked about the rest
    got, left = _ask(upfront, ctx)
    return (decisions + got, [f for f in left if f.required],
            [f for f in gaps if not f.required and f not in upfront] + [f for f in left if not f.required])


def run_board(page, board, ctx):
    ctx = dict(ctx)
    ctx.setdefault("intended_url", page.url)     # the job page this run set out for (apply.py passes args.url)
    res = {"url": page.url, "job_id": ctx.get("job_id"), "board": board["id"], "submitted": False,
           "stopped_reason": None, "decisions": [], "pending_human": []}
    done_decisions = []
    log = BoardRunLog(ctx.get("run_dir"))           # screenshots + steps for the tracker
    run_trace.start("board_run", board=board["id"], probe=bool(ctx.get("probe")),
                    run_dir=ctx.get("run_dir"))     # trace start first; stop() below closes it on every exit
    assist = ctx.get("assist")                      # opt-in Claude help at dead ends (orchestrator/claude_assist.py)

    def stop(reason, pg):
        res.update(stopped_reason=reason, url=pg.url, submitted=reason == "submitted",
                   decisions=[dataclasses.asdict(d) for d in done_decisions])
        if ctx.get("eligibility"):
            res["eligibility"] = ctx["eligibility"]
        log.finish(pg, reason, res["pending_human"])
        # one final trace record for the whole board pass; every return passes through stop()
        run_trace.end("board_run", "done", stopped_reason=reason, url=getattr(pg, "url", None),
                      shot=(log.steps[-1]["screenshot"] if log.steps else None))
        return res

    blocked = _blocked(page, board)
    if blocked and ctx.get("human_wait_s"):
        from ..browser.gate_probe import wait_for_human
        job_url = page.url
        if wait_for_human(page, lambda: _blocked(page, board), ctx["human_wait_s"], what=blocked.replace("_", " ")):
            if page.url.split("?")[0] != job_url.split("?")[0]:
                page.goto(job_url, wait_until="domcontentloaded")      # a login may have left the job page
                page.wait_for_timeout(2000)
            blocked = _blocked(page, board)
    if blocked:
        return stop(blocked, page)
    try:
        state = _posting_state(page, page.evaluate("document.body ? document.body.innerText.slice(0, 6000) : ''"))
    except Exception:
        state = None
    if state:
        return stop(state, page)
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
        legs = _entry_legs(board)
        clicked, err = None, None
        run_trace.start("entry_chain", legs=len(legs))   # on disk before any leg is clicked
        for leg in legs:
            entry = page.locator(leg["selector"]).filter(visible=True).first
            try:
                try:
                    if len(legs) > 1 and not entry.is_visible():
                        continue            # a chain leg not on this page: the next leg decides
                    entry.click(timeout=8000, no_wait_after=True)
                except Exception:
                    # Covered control (Instahyre lays an "Apply now" link over its
                    # button): click what is on top at its centre, as a person would.
                    entry.evaluate("""e => { const r = e.getBoundingClientRect();
                        const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
                        (top || e).click(); }""", timeout=5000)
                clicked, err = leg, None
                break
            except Exception as e:
                err = e                     # a visible leg may be unclickable: a later leg still can
        if clicked is not None:
            res["entry"] = {"leg": clicked.get("leg") or "selector"}    # which leg fired, for the run log
        else:
            if _form_already_open(page):
                ctx["baseline"] = set()           # an earlier run left the form open: every field on it is the form's
            elif not (assist and assist.recover(page, "no_entry")):     # a recovery click replaces the entry click
                res["error"] = (f"{type(err).__name__}: {str(err)[:300]}" if err else "no entry leg on the page")
                return stop("no_entry", page)
        run_trace.end("entry_chain", "done")             # no_entry stop leaves the start dangling on purpose
        page.wait_for_timeout(3000)
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
        clicked_sig = None
        retried_bounce = False
        for _ in range(MAX_STEPS):
            if confirmed(board, cap.responses, page.url):
                break
            from ..browser.clicks import wait_until_stable
            wait_until_stable(page)                   # the step may still be drawing after the URL changed
            from ..browser.page_health import recover
            if recover(page, ctx["intended_url"]) == "dead":
                return stop("dead_page", page)        # Chrome's error shell and the fresh GET already failed once
            blocked = _blocked(page, board)
            if blocked:
                return stop(blocked, page)
            if not on_board(page.url, board):
                return stop("left_board", page)     # e.g. "Apply on company site": another engine takes over
            if is_wall(page, page.url):
                run_trace.start("wall_check")       # the start hits disk before the wall-clearing risk
                # A login / sign-up wall is never a question for a human, and never
                # reaches the perception below. One pass of the board ctx's
                # credential provider (guest apply -> stored creds -> register,
                # clear_auth_wall's contract), then the wall is re-checked: still
                # walled -> stop as before. After form work started there is no
                # rewinding into an account flow.
                if done_decisions:
                    run_trace.end("wall_check", "done", outcome="walled_after_fill")
                    return stop("auth_wall", page)
                _wall_tabs = list(page.context.pages)
                clear_auth_wall(page, ctx.get("cred_provider"))
                page = new_tab_since(page, _wall_tabs)        # guest apply may continue in a fresh tab
                page.wait_for_timeout(1500)                   # the provider's last hop may still be settling
                if is_wall(page, page.url):
                    run_trace.end("wall_check", "done", outcome="still_walled")
                    return stop("auth_wall", page)
                run_trace.end("wall_check", "done", outcome="cleared")
                continue
            ctx["page_index"] = log.page(page)
            run_trace.start("perceive_fields")           # the driver's read of the screen, on disk before it happens
            fields, blocked = split_sensitive(driver.fields(page, board, ctx, cap))
            run_trace.end("perceive_fields", "done", fields=len(fields), sensitive=len(blocked))
            if any(f.required for f in blocked):          # bank / ID details: yours to fill, never asked
                res["pending_human"] = [dataclasses.asdict(f) for f in blocked if f.required]
                return stop("sensitive_field", page)
            sig = (page.url, tuple(sorted((f.label, f.kind) for f in fields)))
            errs = _visible_errors(page) if clicked_sig is not None and sig == clicked_sig else []
            bounced = bool(errs)       # same fields back and the board shows an error: it rejected an answer (a slow page is the stuck path)
            ctx["fill_first"] = None if ctx.get("probe") else (lambda ds: driver.put(page, board, ctx, fields, ds))
            decisions, needs, optional = _answers(fields, board, driver, cap, ctx)
            if bounced:
                # Next/Continue was clicked but the form did not move on: the board
                # rejected something. Once: answer this page's open "optional"
                # fields (declarations affirmatively, the rest from the human),
                # then retry. Otherwise stop instead of refilling in a loop.
                extra = _affirm(optional) if not retried_bounce else []
                rest = [f for f in optional if f.ref not in {d.ref for d in extra}]
                if not retried_bounce and rest:
                    got, _ = _ask(rest, ctx)
                    extra += got
                if retried_bounce or not extra:
                    res["error"] = "; ".join(errs)
                    return stop("validation_error", page)
                retried_bounce = True
                decisions += extra
            if ctx.get("probe"):
                # Probe: report what would be filled / asked on the first form
                # page, then stop — nothing typed, nothing submitted.
                done_decisions += decisions
                res["pending_human"] = [dataclasses.asdict(f) for f in needs + optional]
                res["fields"] = [dataclasses.asdict(f) for f in fields]
                return stop("probe", page)
            if needs:
                if not ctx.get("probe"):
                    driver.put(page, board, ctx, fields, decisions)     # leave the page as full as the answers allow
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
                    page.wait_for_timeout(1500)
                    continue
            if nxt is None:
                _tabs_before = list(page.context.pages)
                if assist and assist.recover(page, "no_advance_control"):
                    page = new_tab_since(page, _tabs_before)   # e.g. "Apply on company website" opened the employer's tab
                    continue
                break
            label, final = nxt
            if final:
                if not _authorized(ctx, board, page, done_decisions):
                    return stop("dry_run", page)
                _untick(page, board)
                irreversible = True
                try:
                    from ..browser.form_values import read_form_values
                    before_submit = read_form_values(page)             # what the form holds as it goes out
                except Exception:
                    before_submit = {}
            from ..browser.clicks import page_signature, wait_for_change
            before_click = page_signature(page)
            _tabs_before = list(page.context.pages)
            clicked_sig = sig
            try:
                driver.click(page, label, ctx)
            except Exception as e:
                # The click often lands and navigates, and only the post-click
                # wait/retry errors (the button detached). Moved on = success.
                page.wait_for_timeout(2000)
                try:
                    now = driver.fields(page, board, ctx, cap)
                    moved = (page.url, tuple(sorted((f.label, f.kind) for f in now))) != sig
                except Exception:
                    moved = False
                if moved:
                    continue
                errs = _visible_errors(page)
                res["error"] = f"could not click {label!r}: {type(e).__name__}" + (f" | page says: {'; '.join(errs)}" if errs else "")
                return stop("validation_error" if errs else "stuck", page)
            page.wait_for_timeout(2500)
            if new_tab_since(page, _tabs_before) is not page:
                page = new_tab_since(page, _tabs_before)          # the step continues in a new tab
                unanswered = 0
                continue
            if page_signature(page) == before_click and not wait_for_change(page, before_click):
                # The page has not answered the click. Clicking again is how a step gets skipped (the second click
                # lands on the page that was merely slow): allow one more wait-and-retry, then stop as stuck.
                unanswered += 1
                if unanswered >= 2:
                    return stop("stuck", page)
            else:
                unanswered = 0
        page.wait_for_timeout(1500)
        ok = confirmed(board, cap.responses, page.url)
        for r in cap.responses[-6:]:           # evidence for the run log: what the board answered
            try:
                body = r.text()[:300].replace("\n", " ")
            except Exception:
                body = "<unreadable>"
            print(f"[board] captured {getattr(r, 'status', '?')} {r.url[:90]} :: {body}", flush=True)
    if ok and irreversible and ctx.get("on_submit"):
        try:
            ctx["on_submit"](before_submit if "before_submit" in locals() else {}, ctx.get("how", "tap"), page.url)
        except Exception:
            pass
    return stop("submitted" if ok else "unconfirmed" if irreversible else "stuck", page)
