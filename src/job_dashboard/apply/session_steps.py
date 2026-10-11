"""The page work behind each agent apply tool. Runs on the browser thread (session_actor); never decides an answer.

Each step reuses the script engine's parts: board drivers and their checks (career_agent/boards), perception and
the filler (career_agent/browser), the answer ladder for suggestions (orchestrator/answering.py). The agent decides;
these read the page, write what it decided, and say what happened."""
from __future__ import annotations

import dataclasses
import json
import re

from career_agent.boards.drivers import DRIVERS
from career_agent.boards.profiles import board_for, on_board
from career_agent.boards.run import _blocked, _form_already_open, _interstitials, _job_location, _needles
from career_agent.boards.signals import confirmed
from career_agent.browser.form_model import Field
from career_agent.browser.clicks import page_signature, timeout_ms, wait, wait_for_change, wait_until_stable
from career_agent.browser.page_prep import (classify_entry, is_application_form, is_login_page, new_tab_since,
                                            prepare, reach_application_form, suppress_noise)
from career_agent.orchestrator.advance import SUBMIT_NAMES, has_control, pick_advance_label
from career_agent.orchestrator.mapper import FillDecision, _action_for_kind
from career_agent.orchestrator.sensitive import is_sensitive
from job_dashboard import agent_browser

_CAPTCHA_FIELD = re.compile(r"captcha|security code|characters (shown )?in the image|type the (text|characters|code)", re.I)
CAPTCHAS = {"recaptcha_v2_checkbox", "recaptcha_v2_image", "hcaptcha_checkbox", "hcaptcha_image",
            "cloudflare_interstitial", "text_challenge"}
MAX_OPTIONS = 20
_TRUE = {"yes", "true", "1", "checked", "y", "on"}


class StepError(Exception):
    """The step could not do what was asked; the message is for the agent."""


def check_dialog(s) -> dict | None:
    """Run after every step. A cookie banner or an idle prompt is handled here; a sign-in dialog or a captcha is a
    wall ({"blocked": ...}); any other dialog goes to the agent ({"dialog": ...}) to answer with apply_dialog."""
    from career_agent.browser import dialogs
    from career_agent.browser.page_prep import _DIALOG_DISMISS, _click_first, dismiss_consent
    d = dialogs.read(s.page)
    if not d:
        return None
    kind = dialogs.classify(d)
    if kind == "captcha":
        return {"blocked": "captcha", "detail": "a captcha dialog"}
    if kind == "login":
        return {"blocked": "account_needed", "detail": f"a sign-in dialog: {d.get('label') or d.get('text', '')[:80]}"}
    if kind == "consent" and dismiss_consent(s.page):
        return {"handled": "declined a cookie banner"}
    if kind == "idle":
        try:
            dialog = s.page.locator("[role=dialog]:visible, [role=alertdialog]:visible").last
            if _click_first(s.page, _DIALOG_DISMISS, within=dialog):
                return {"handled": "dismissed an idle prompt"}
        except Exception:
            pass
    return {"dialog": {"kind": kind, "title": d.get("label", ""), "text": d.get("text", ""), "buttons": d.get("buttons", []),
                       "has_fields": bool(d.get("inputs")),
                       "next": "answer it with apply_dialog (one of its buttons), or fill its fields first"}}


def _with_dialog(s, out: dict) -> dict:
    """`out` plus what a dialog over the page needs; a wall replaces it."""
    found = check_dialog(s)
    if not found:
        return out
    if found.get("blocked"):
        return found
    return {**out, **found}


def press_dialog(s, button: str) -> dict:
    from career_agent.browser import dialogs
    try:
        dialogs.press(s.page, button)
    except ValueError as e:
        raise StepError(str(e))
    return {"pressed": button}


def gate(s) -> str | None:
    """A captcha / bot check on the page (detected, never solved), else None."""
    try:
        g = s.ctx["deps"].gate(s.page)
    except Exception:
        return None
    return g if g in CAPTCHAS else None


def _target_id(page) -> str | None:
    try:
        return page.context.new_cdp_session(page).send("Target.getTargetInfo")["targetInfo"]["targetId"]
    except Exception:
        return None


def start(s, context) -> dict:
    """Open the job's page in a new background tab of the agent Chrome; what kind of page it is."""
    s.page = agent_browser.background_tab(context)
    try:
        resp = s.page.goto(s.url, wait_until="domcontentloaded", timeout=timeout_ms(45000))
    except Exception as e:
        return {"blocked": "unreachable", "detail": f"{type(e).__name__}: {str(e)[:200]}"}
    try:
        s.page.wait_for_load_state("networkidle", timeout=timeout_ms(8000))
    except Exception:
        pass
    s.tab_target_id = _target_id(s.page)
    prepare(s.page)
    s.kind = classify_entry(s.page, status=resp.status if resp else None)
    if s.kind == "closed":
        return {"blocked": "closed"}
    try:
        text = (s.page.inner_text("body") or "")[:5000]
    except Exception:
        text = ""
    job = s.ctx.get("job") or {}
    if not job.get("description") and text:
        s.ctx["job"] = {**job, "description": text}
    s.board = board_for(s.page.url) or board_for(s.url)
    captcha = gate(s)
    if captcha:
        return {"blocked": "captcha", "detail": captcha}
    return {"url": s.page.url, "title": _title(s.page), "board": s.board["id"] if s.board else None, "entry": s.kind}


def _title(page) -> str:
    try:
        return page.title()[:120]
    except Exception:
        return ""


def reach(s) -> dict:
    """Get from the job page to the application form; on a board, open its apply dialog."""
    if s.board:
        out = _enter_board(s)
        if out.get("blocked") != "left_board":
            return out
        s.board, s.cap = None, _close_capture(s.cap)  # "Apply on company site": the rest is a career site
    page = s.page
    if s.kind == "none" or not is_application_form(page):
        from career_agent.browser.page_prep import _hop, find_apply_affordance, login_dialog_open
        aff = find_apply_affordance(page)
        if aff is not None:                        # the first hop by hand: a sign-in wall right after it is the answer
            s.page = page = _hop(page, aff)
            if login_dialog_open(page) or is_login_page(page):
                return {"blocked": "account_needed", "detail": f"\"{aff['name']}\" asks you to sign in to the site first"}
    if not is_application_form(page):
        s.page, _ = reach_application_form(page)
        prepare(s.page)
        s.kind = classify_entry(s.page)
        s.tab_target_id = _target_id(s.page) or s.tab_target_id
    s.tab_target_id = _target_id(s.page) or s.tab_target_id   # the Apply hop may have opened the form in a new tab
    if s.kind == "closed":
        return {"blocked": "closed"}
    captcha = gate(s)
    if captcha:
        return {"blocked": "captcha", "detail": captcha}
    from career_agent.browser.page_prep import login_dialog_open
    if is_login_page(s.page) or login_dialog_open(s.page):
        return {"blocked": "account_needed", "detail": "the site wants you to sign in before applying"}
    return _with_dialog(s, {"on_form": is_application_form(s.page), "url": s.page.url, "title": _title(s.page)})


def _close_capture(cap):
    if cap is not None:
        try:
            cap.__exit__(None, None, None)
        except Exception:
            pass
    return None


def _enter_board(s) -> dict:
    from job_dashboard.sources.cdp.session import Capture
    page, board = s.page, s.board
    blocked = _blocked(page, board)
    if blocked:
        return {"blocked": "captcha" if blocked == "challenge" else "logged_out"}
    if board["entry"].get("submits", "no") != "no":
        return {"blocked": "one_click_entry", "detail": "this board submits on the Apply click itself"}
    s.ctx["baseline"] = {(f.label, f.kind) for f in s.ctx["deps"].snapshot(page)}
    s.cap = Capture(page.context, _needles(board)).__enter__()   # held open until the run ends: submit proof
    before = list(page.context.pages)
    try:
        page.locator(board["entry"]["selector"]).filter(visible=True).first.click(timeout=timeout_ms(15000),
                                                                                    no_wait_after=True)
    except Exception:
        if not _form_already_open(page):
            # The board's own apply flow isn't offered on this posting (Indeed's "Apply on company site", LinkedIn's
            # plain "Apply"): carry on as a career site, which follows the page's own apply link.
            return {"blocked": "left_board", "url": page.url, "detail": "no board apply control; following the site's own"}
        s.ctx["baseline"] = set()
    wait(page, 3000)
    s.page = new_tab_since(page, before)
    if s.page is not page:
        s.tab_target_id = _target_id(s.page) or s.tab_target_id
    _interstitials(s.page, board)
    try:
        s.ctx["job_location"] = _job_location(s.page.evaluate("document.body.innerText"))
    except Exception:
        pass
    if not on_board(s.page.url, board):
        return {"blocked": "left_board", "url": s.page.url}
    if is_login_page(s.page):
        return {"blocked": "logged_out"}
    return _with_dialog(s, {"on_form": True, "url": s.page.url, "title": _title(s.page), "board": board["id"]})


# ── reading the form ─────────────────────────────────────────────────────────────────────────────────────────────

class _QuietDeps:
    """The browser ops with a lighter read: the harness re-reads a page after every step, so it scrolls through a page
    (to wake lazy fields) only the first time it sees it and takes no debug screenshot. All else is BrowserDeps."""

    def __init__(self, deps, s):
        self._deps, self._s = deps, s

    def __getattr__(self, name):
        return getattr(self._deps, name)

    def snapshot(self, page):
        from career_agent.browser.perception import snapshot_form
        key = (page.url.split("#")[0], self._s.step)
        first = key not in self._s.scrolled
        self._s.scrolled.add(key)
        return snapshot_form(page, scroll=first, shot=False)


def _deps(s):
    d = s.ctx["deps"]
    return d if isinstance(d, _QuietDeps) else s.ctx.setdefault("_quiet", _QuietDeps(d, s))


def _all_fields(s) -> list:
    if s.board:
        return DRIVERS[s.board["archetype"]]._snapshot(s.page, {**s.ctx, "deps": _deps(s)})
    return suppress_noise(_deps(s).snapshot(s.page))


def _values(s, fields) -> dict:
    from career_agent.browser.filler import read_back
    probe = [FillDecision(f.ref, f.kind, f.label, None, _action_for_kind(f.kind), "") for f in fields]
    try:
        return read_back(s.page, probe)
    except Exception:
        return {}


class _QuietQA:
    """What the answer ladder needs to find the user's earlier answers, without recording a suggestion as filled."""

    def __init__(self, qa):
        self.conn, self.job_id, self.run_key = qa.conn, qa.job_id, qa.run_key
        self.page = None

    def trace_all(self, fields): pass
    def decision(self, d): pass
    def needs(self, f): pass


def snapshot(s) -> dict:
    """The current page's fields as the agent sees them: short ids, current values, and a grounded suggestion."""
    if s.board and s.cap is not None and confirmed(s.board, s.cap.responses, s.page.url):
        return {"submitted_confirmed": True}
    captcha = gate(s)
    if captcha:
        return {"blocked": "captcha", "detail": captcha}
    if s.board:
        blocked = _blocked(s.page, s.board)
        if blocked:
            return {"blocked": "captcha" if blocked == "challenge" else "logged_out"}
    wait_until_stable(s.page)
    found = check_dialog(s)
    if found and found.get("blocked"):
        return found
    every = _all_fields(s)
    fields = [f for f in every if f.kind != "button"]
    asks = next((f.label for f in fields if _CAPTCHA_FIELD.search(f.label or "")), None)
    if asks:
        # an image captcha typed into a plain box (Zoho Recruit) has no widget for gate() to find
        return {"blocked": "captcha", "detail": f"the form asks for a captcha ({asks.strip()[:60]!r})"}
    buttons = [f.label for f in every if f.kind == "button" and f.label]
    fields += _resume_upload(fields, buttons)
    safe = [f for f in fields if not is_sensitive(f)]
    from career_agent.orchestrator.answering import answer_fields
    ladder = {"learn": s.ctx.get("learn"), "profile": s.ctx["profile"], "resume_pdf": s.ctx.get("resume_pdf"),
              "qa": _QuietQA(s.qa) if s.qa else None}
    try:
        suggested, _ = answer_fields(safe, ladder)
    except Exception as e:
        print(f"[apply-session] suggestions failed: {type(e).__name__}: {e}", flush=True)
        suggested = []
    by_ref = {d.ref: d for d in suggested}
    by_ref.update({d.ref: d for d in _resume_choices(s, safe) if d.ref not in by_ref})
    values = _values(s, fields)
    s.fields, s.suggest = {}, {}
    out = []
    for i, f in enumerate(fields, 1):
        fid = f"f{i}"
        s.fields[fid] = f
        row = {"id": fid, "label": (f.label or "").strip()[:300], "kind": f.kind, "required": f.required}
        if f.options:
            row["options"] = f.options[:MAX_OPTIONS]
            if len(f.options) > MAX_OPTIONS:
                row["more_options"] = len(f.options) - MAX_OPTIONS
        if f.max_length:
            row["max_length"] = f.max_length
        if values.get(f.ref):
            row["value"] = str(values[f.ref])[:300]
        if is_sensitive(f):
            row["sensitive"] = True                # bank / ID detail: never filled by the agent
        elif f.ref in by_ref:
            d = by_ref[f.ref]
            s.suggest[fid] = d
            row["suggestion"] = {"value": d.value if d.action != "upload" else "your résumé (file)",
                                 "source": d.source}
        out.append(row)
    page = {"step": s.step, "url": s.page.url, "title": _title(s.page), "fields": out,
            "controls": buttons[:15], "next": _advance_label(s, every), "submit": _submit_label(s, every)}
    return {**page, **found} if found else page


def _is_resume_list(f) -> bool:
    opts = f.options or []
    return f.kind in ("radio_group", "select", "combobox") and bool(opts) \
        and all(re.search(r"\.(pdf|docx?)\b", o, re.I) for o in opts)


_UPLOAD_RESUME = re.compile(r"^\s*upload (a )?(resume|résumé|cv)\s*$", re.I)


def _resume_upload(fields, buttons) -> list:
    """LinkedIn's résumé step lists every résumé ever uploaded (several with the same name, years old) and offers an
    "Upload resume" button with no <input type=file> behind it. Show that button as a file field, so the agent
    uploads the current résumé instead of picking an old one off the list."""
    up = next((b for b in buttons if _UPLOAD_RESUME.match(b)), None)
    if up is None or not any(_is_resume_list(f) for f in fields):
        return []
    return [Field(f"button:{up}", "file", up, False, [], None, "resume")]


def _resume_choices(s, fields) -> list:
    """Suggest the user's current résumé on a "pick one of your résumés" step: upload it where the page can take an
    upload, else pick it off the list by file name when exactly one entry has that name. Never a guess."""
    import os
    name = os.path.basename(str(s.ctx.get("resume_pdf") or ""))
    if not name:
        return []
    upload = [f for f in fields if f.kind == "file" and f.ref.startswith("button:")]
    if upload:
        f = upload[0]
        return [FillDecision(f.ref, f.kind, f.label, s.ctx["resume_pdf"], "upload_chooser", "resume")]
    return [FillDecision(f.ref, f.kind, f.label, name, _action_for_kind(f.kind), "resume")
            for f in fields if _is_resume_list(f) and (f.options or []).count(name) == 1]


def _advance_label(s, every):
    if s.board:
        nxt = DRIVERS[s.board["archetype"]].next_control(s.page, s.board, s.ctx)
        return nxt[0] if nxt and not nxt[1] else None
    label = pick_advance_label(every, is_last=False)
    return None if label is None or _is_submit(label) else label


def _submit_label(s, every):
    if s.board:
        nxt = DRIVERS[s.board["archetype"]].next_control(s.page, s.board, s.ctx)
        return nxt[0] if nxt and nxt[1] else None
    label = pick_advance_label(every, is_last=True)
    return label if label and _is_submit(label) else None


def _is_submit(label: str) -> bool:
    return has_control([Field("b", "button", label, False, [], None, None)], SUBMIT_NAMES)


# ── writing ──────────────────────────────────────────────────────────────────────────────────────────────────────

def decision_for(s, f, value, source) -> FillDecision:
    if f.kind == "file":
        if not s.ctx.get("resume_pdf"):
            raise StepError("no résumé on file to upload")
        how = "upload_chooser" if f.ref.startswith("button:") else "upload"     # a button that opens the file picker
        return FillDecision(f.ref, f.kind, f.label, s.ctx["resume_pdf"], how, source)
    if f.kind == "checkbox":
        return FillDecision(f.ref, f.kind, f.label, str(value).strip().lower() in _TRUE, "check", source)
    return FillDecision(f.ref, f.kind, f.label, value, _action_for_kind(f.kind), source)


def behind_dialog(s, refs) -> list[str]:
    """Of these field refs, the ones under an open dialog (not inside it): typing there goes nowhere, since a modal
    keeps the keyboard focus inside itself."""
    from career_agent.browser import dialogs
    from career_agent.browser.perception import frame_target
    if not dialogs.read(s.page):
        return []
    out = []
    for ref in refs:
        try:
            target, sel = frame_target(s.page, ref)
            inside = target.locator(sel).first.evaluate(
                "e => !!e.closest('[role=dialog],[role=alertdialog],[aria-modal=true],dialog[open]')", timeout=1500)
        except Exception:
            inside = True                          # can't tell: let the fill try
        if not inside:
            out.append(ref)
    return out


def put(s, decisions) -> None:
    if s.board:
        DRIVERS[s.board["archetype"]].put(s.page, s.board, s.ctx, list(s.fields.values()), decisions)
    else:
        s.ctx["deps"].fill(s.page, decisions)


def did_not_stick(s, decisions) -> list[str]:
    from career_agent.browser.filler import read_back
    texts = [d for d in decisions if d.action == "fill" and d.value not in (None, "")]
    try:
        shown = read_back(s.page, texts)
    except Exception:
        return []
    return [d.label for d in texts if d.ref in shown and not str(shown[d.ref]).strip()]


# ── moving on ────────────────────────────────────────────────────────────────────────────────────────────────────

def advance(s) -> dict:
    every = _all_fields(s)
    label = _advance_label(s, every)
    if label is None:
        if _submit_label(s, every):
            raise StepError("this is the last page: the only control left submits. Use apply_submit.")
        raise StepError("no Next/Continue control on this page (a required field may be blank, or the page "
                        "needs a different click: read apply_page_text)")
    before = page_signature(s.page)
    _click(s, label)
    # A career-site click already waits for the page to answer (settle_after_click); a board driver's click doesn't.
    changed = page_signature(s.page) != before
    if not changed and s.board:
        wait(s.page, 2000)
        changed = page_signature(s.page) != before or wait_for_change(s.page, before)
    if changed:
        s.step += 1
    out = _with_dialog(s, {"clicked": label, "changed": bool(changed), "url": s.page.url})
    if s.board and not on_board(s.page.url, s.board):
        s.board, s.cap = None, _close_capture(s.cap)
        out["left_board"] = True
    return out


def _click(s, label) -> None:
    if s.board:
        DRIVERS[s.board["archetype"]].click(s.page, label, s.ctx)
    else:
        s.ctx["deps"].click(s.page, label)


def submit_click(s) -> tuple[bool, str]:
    """Click the final control; (confirmed, why) from the board's own response or the page's confirmation."""
    every = _all_fields(s)
    label = _submit_label(s, every)
    if label is None:
        raise StepError("no Submit control on this page yet: finish the earlier pages with apply_advance")
    _click(s, label)
    if s.board and s.cap is not None:
        for _ in range(12):
            wait(s.page, 1500)
            if confirmed(s.board, s.cap.responses, s.page.url):
                return True, f"{s.board['id']} confirmed the application"
        return False, "the board did not confirm the application"
    return s.ctx["deps"].confirmed(s.page)


def page_text(s, limit: int = 6000) -> str:
    try:
        return (s.page.inner_text("body") or "")[:limit]
    except Exception as e:
        return f"(could not read the page: {type(e).__name__})"


def as_json(obj) -> str:
    return json.dumps(dataclasses.asdict(obj) if dataclasses.is_dataclass(obj) else obj, default=str)
