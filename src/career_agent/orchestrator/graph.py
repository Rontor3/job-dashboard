"""LangGraph-based career agent graph.

Nodes: classify → cred_provide → reach → perceive → fill → human_gate → advance
Page lives outside state (Playwright isn't serialisable) — pass via
config["configurable"]["page"].  Human gates use interrupt(); the outer loop
in apply.py handles the Telegram collect → Command(resume=answers) cycle.
SqliteSaver checkpoints every node transition so the logical state survives.
"""
from __future__ import annotations

import dataclasses
import re
import time
from typing import TypedDict

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt

from .. import run_trace


# ── State ─────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    url: str
    job_id: int | None
    jd_text: str | None
    kind: str               # classify_entry result
    ats_vendor: str | None  # vendor label from ats-graph (e.g. "Lever", "Workday")
    steps: int
    max_steps: int
    do_submit: bool
    autonomous: bool
    cred_provided: bool     # True after cred_provide ran (prevents re-triggering)
    cred_action: str | None      # "guest" | "register" | "login" from the last cred_provide
    gate_notice: dict | None     # {"gate", "attempted", "sent", "resolved"} from the last gate stop
    # current screen snapshot (serialised Field dicts); reset each perceive pass
    form: list[dict]
    form_sig: str | None    # for stuck-detection in advance
    # fields needing human input this cycle (serialised Field dicts)
    pending_human: list[dict]
    # accumulated FillDecision dicts across all screens
    decisions: list[dict]
    # assembled between nodes; add new keys here or LangGraph drops them
    submitted: bool
    stopped_reason: str | None
    site_said: str | None       # the site's own refusal words on stopped_reason="site_refused"
    # screen signatures the validation refill already ran once for (stop double rounds)
    refilled: list[str]


def initial_state(url: str, *, job_id=None, jd_text=None,
                  do_submit=False, autonomous=False, max_steps=15) -> AgentState:
    return {
        "url": url, "job_id": job_id, "jd_text": jd_text,
        "kind": "", "ats_vendor": None, "steps": 0, "max_steps": max_steps,
        "do_submit": do_submit, "autonomous": autonomous,
        "cred_provided": False, "cred_action": None, "gate_notice": None,
        "form": [], "form_sig": None,
        "pending_human": [], "decisions": [],
        "submitted": False, "stopped_reason": None, "site_said": None, "refilled": [],
    }


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _f2d(f) -> dict:
    return dataclasses.asdict(f)


def _d2f(d: dict):
    from ..browser.form_model import Field
    return Field(**d)


def _dec2d(d) -> dict:
    return dataclasses.asdict(d)


def _d2dec(d: dict):
    from ..orchestrator.mapper import FillDecision
    return FillDecision(**d)


# ── Memory helpers ────────────────────────────────────────────────────────────

def _gate_sender(c) -> object | None:
    """A channel that can physically deliver a notice right now. The captcha-link
    sender first; else the collector's own Telegram notify (park mode wires
    client.send_message there); else a Telegram collector's client. None only
    when no Telegram channel is wired at all — a CLI/offline run has a human in
    the room."""
    on_link = c.get("on_link")
    if on_link is not None:
        return on_link
    col = c.get("collector")
    if col is None:
        return None
    notify = getattr(col, "notify", None)
    if notify:
        return notify
    client = getattr(col, "client", None)
    if client is not None and hasattr(client, "send_message"):
        return lambda text: client.send_message(text)
    return None


_NOTIFY_RETRY_S, _NOTIFY_TRIES = 0.5, 3

def _notify_gate(c, gate: str, message: str) -> dict:
    """Deliver `message` via the run's Telegram channel. Never raises; never
    skipped when the channel merely looks down: Telegram sends are idempotent
    text, so a failed attempt is retried, and if every attempt fails the
    gate_notice records queued=True — the run's result then says honestly that
    a human must look (rather than 'notified: False' over a blip)."""
    sender = _gate_sender(c)
    if sender is None:
        return {"attempted": False, "sent": False, "queued": False}
    for attempt in range(1, _NOTIFY_TRIES + 1):
        try:
            sender(message)
            return {"attempted": True, "sent": True, "queued": False}
        except Exception as e:
            print(f"[notify] on_link failed (attempt {attempt}/{_NOTIFY_TRIES}): {e!r}", flush=True)
            if attempt < _NOTIFY_TRIES:
                time.sleep(_NOTIFY_RETRY_S * attempt)
    return {"attempted": True, "sent": False, "queued": True}


# ── Nodes ─────────────────────────────────────────────────────────────────────

def classify_node(state: AgentState, config) -> dict:
    c = config["configurable"]
    page = c["page"]
    if c.get("prep_fn"):
        c["prep_fn"](page)

    # Security-email gate: stop immediately if the site has flagged our account.
    try:
        from urllib.parse import urlparse
        from ..integrations.inbox_watch import check_security_email
        from ..reliability.portal_state import PortalState
        _domain = urlparse(page.url).netloc
        if _domain and check_security_email(_domain):
            PortalState().record_outcome(_domain, "blocked")
            return {"kind": "closed", "stopped_reason": "security_email",
                    "url": page.url, "jd_text": state.get("jd_text"), "ats_vendor": None}
    except Exception:
        pass  # never let inbox watch block a run

    from ..browser.page_prep import classify_entry
    from ..browser.ats_lookup import lookup as _ats_lookup
    kind = classify_entry(page)
    jd_text = state.get("jd_text")
    if not jd_text and kind != "closed":
        try:
            jd_text = (page.inner_text("body") or "")[:5000].strip() or None
        except Exception:
            jd_text = None
    # Wire jd_text into TelegramCollector and judgment context if present
    collector = c.get("collector")
    if jd_text and collector and hasattr(collector, "jd_text"):
        collector.jd_text = jd_text
    jctx = c.get("judgment_ctx")
    if jd_text and jctx is not None and not jctx.resume_text:
        jctx.resume_text = jd_text[:2000]  # give qwen JD context for essay answers
    # ATS knowledge graph lookup — vendor notes flow into judgment tier
    vendor = _ats_lookup(page.url)
    ats_vendor = vendor["label"] if vendor else None
    if ats_vendor:
        notes = vendor.get("notes") or ""
        hints = vendor.get("fix_hints") or []
        hint_str = " | fixes: " + "; ".join(hints[:2]) if hints else ""
        print(f"[ats] {ats_vendor}: {notes[:80]}{hint_str}", flush=True)
    return {"kind": kind, "jd_text": jd_text, "url": page.url, "ats_vendor": ats_vendor}


def cred_provide_node(state: AgentState, config) -> dict:
    c = config["configurable"]
    from ..browser.credential_provider import provide as _provide
    from ..browser.page_prep import classify_entry, clear_auth_wall, is_application_form, enter_application, prepare, reach_application_form
    original_url = state["url"]

    _prof = c.get("profile")
    _email = _prof.contact.get("email", "") if _prof and hasattr(_prof, "contact") else ""
    _phone = _prof.contact.get("phone", "") if _prof and hasattr(_prof, "contact") else ""

    # reach_node may have opened a new tab (e.g. Taleo login); resolve the
    # actual current page from state["url"] so provide() runs on the right tab.
    _base = c["page"]
    page = _base
    _target = state.get("url", "")
    if _target and _target != _base.url:
        for _p in _base.context.pages:
            if _p.url == _target:
                page = _p
                break
        else:
            page = _base                       # no tab at that url: stay on this job's own tab, not 'the last tab'

    # Run perceive_node on the login/signup page first so its captcha check
    # and remote-solve logic fires before we attempt to fill credentials.
    perceive_update = perceive_node(state, config)
    if perceive_update.get("stopped_reason"):
        return {**perceive_update, "cred_provided": False}

    _cred_result: dict = {}

    def _prov(pg, gate, site):
        handled, action = _provide(pg, gate, site, original_url=original_url, email=_email, phone=_phone,
                                   collector=c.get("collector"))
        _cred_result["action"] = action
        return handled

    # Auth wall reached — notify via Telegram then proceed with auto-login.
    on_link = c.get("on_link")
    if on_link:
        try:
            on_link(f"🔐 Login wall on {page.url[:80]} — attempting auto-login")
        except Exception:
            pass
    print(f"[auth-wall] {page.url[:80]}", flush=True)

    cleared = clear_auth_wall(page, credential_provider=_prov)
    cred_action = _cred_result.get("action")
    if not cleared and cred_action in ("register", "register_inline", "login"):
        # A password box inside a long application form is registration+application in one page, not a wall left
        # standing: the credentials are in, the filler completes the rest (same rule the plain walk() path applies).
        from ..browser.credential_provider import _is_combined_form
        if is_application_form(page) and _is_combined_form(page):
            print("[auth-wall] registration is part of the application form — continuing to fill", flush=True)
            cleared = True
    if not cleared:
        # otp_unanswered: the provider asked the connected human once and was
        # silent within the short window — an honest park, the queue re-drains it.
        reason = cred_action if cred_action == "otp_unanswered" else "auth_wall"
        return {"stopped_reason": reason, "cred_provided": True, "cred_action": cred_action}
    kind = classify_entry(page)
    # After registration Darwinbox lands back on the JD page — re-enter apply
    if kind in ("none", "form") and not is_application_form(page):
        page, _ = reach_application_form(page)
        if c.get("prep_fn"):
            c["prep_fn"](page)
        kind = classify_entry(page)
    if kind == "password" and is_application_form(page):
        kind = "form"
    return {"kind": kind, "url": page.url, "cred_provided": True, "cred_action": cred_action}


def tailor_cv_node(state: AgentState, config) -> dict:
    from .tailor_cv import tailor_cv_node as _tailor
    return _tailor(state, config)


def reach_node(state: AgentState, config) -> dict:
    c = config["configurable"]
    page = c["page"]
    from ..browser.page_prep import reach_application_form, classify_entry
    page, _ = reach_application_form(page)
    if c.get("prep_fn"):
        c["prep_fn"](page)
    return {"kind": classify_entry(page), "url": page.url}


@run_trace.traced("perceive")    # each perception pass is a trace step (triage O1); also covers cred_provide's inner pass
def perceive_node(state: AgentState, config) -> dict:
    """Gate check + overlay cleanup. Blocks if gate unresolvable."""
    if state.get("stopped_reason"):
        return {}
    c = config["configurable"]
    page = c["page"]
    deps = c["deps"]
    if c.get("prep_fn"):
        c["prep_fn"](page)
    try:
        from ..browser.clicks import wait_until_stable
        wait_until_stable(page)              # read the step that is on screen, not the one that is going away
    except Exception:
        pass

    from ..browser.page_health import recover
    if recover(page, c.get("intended_url") or state.get("url") or page.url) == "dead":
        return {"stopped_reason": "dead_page"}      # Chrome's error shell; the one fresh GET already failed

    from ..browser.page_prep import dismiss_consent
    from ..browser.gate_probe import HANDLERS
    dismiss_consent(page)          # clear async cookie banners before gate check
    page.wait_for_timeout(2000)
    gate = deps.gate(page)
    _INTERACTIVE = {"recaptcha_v2_checkbox", "recaptcha_v2_image",
                    "hcaptcha_checkbox", "hcaptcha_image"}
    _SUBMIT_GATED = {"hcaptcha_checkbox"}   # invisible widget; form still accessible
    _EARLY_BLOCK = {"cloudflare_interstitial", "otp_sms", "text_challenge"}
    _submit_gate_notice = None
    from ..browser.gate_probe import HANDLERS
    if gate in _INTERACTIVE:
        # Poll up to 5s for auto-verify (trusted-browser self-solve).
        for _ in range(5):
            page.wait_for_timeout(1000)
            gate = deps.gate(page)
            if HANDLERS.get(gate, "escalate") == "proceed":
                break
    if gate in _EARLY_BLOCK and c.get("human_wait_s"):
        from ..browser.gate_probe import wait_for_human
        if wait_for_human(page, lambda: deps.gate(page) in _EARLY_BLOCK, c["human_wait_s"], what=gate.replace("_", " ")):
            gate = deps.gate(page)
    if gate in _EARLY_BLOCK:
        notice = _notify_gate(c, gate, f"⛔ {gate} on {page.url[:80]} — agent stopped, needs your attention")
        return {"stopped_reason": f"gate:{gate}",
                "gate_notice": {"gate": gate, "resolved": False, **notice}}
    if gate == "otp_email":
        notice = _notify_gate(c, "otp_email", f"📧 OTP email required on {page.url[:80]} — agent stopped")
        return {"stopped_reason": "gate:otp_email",
                "gate_notice": {"gate": "otp_email", "resolved": False, **notice}}
    # Blocking visual challenge (image captcha) — remote-solve via Telegram.
    if gate in _INTERACTIVE and gate not in _SUBMIT_GATED:
        if HANDLERS.get(gate, "escalate") != "proceed":
            human = c["human"]
            on_link = _gate_sender(c) or (lambda u: None)
            _notifier = c.get("remote_solve_notifier")
            print(f"[gate] {gate} — sending live-view link via Telegram...", flush=True)
            result = human.remote_solve(page, gate, on_link,
                                        **({"notifier": _notifier} if _notifier is not None else {}))
            if not result:
                return {"stopped_reason": f"gate:{gate}",
                        "gate_notice": {"gate": gate, "attempted": c.get("on_link") is not None,
                                        "sent": result.sent, "resolved": result.resolved}}
            if HANDLERS.get(deps.gate(page), "escalate") != "proceed":
                return {"stopped_reason": f"gate:{gate}",
                        "gate_notice": {"gate": gate, "attempted": True,
                                        "sent": result.sent, "resolved": result.resolved}}
    # Submit-gated captcha (e.g. hcaptcha_checkbox): form is accessible but captcha
    # blocks submit. Alert immediately so the human is watching before field questions arrive.
    if gate in _SUBMIT_GATED and HANDLERS.get(gate, "escalate") != "proceed":
        notice = _notify_gate(c, gate, f"⚠️ {gate} detected on {page.url[:80]}\n"
                              "I'm filling the form now — live-view link will follow when ready to submit.")
        print(f"[gate] {gate} on form (submit-gated) — notified: {notice['sent']}", flush=True)
        # Doesn't stop the run (form stays fillable) — stash for the eventual
        # stop/submit step to report, since this gate's own path continues below.
        _submit_gate_notice = {"gate": gate, "resolved": False, **notice}

    # Navigation rule: scroll to top + screenshot before reading DOM
    from .step_engine import _page_survey
    _page_survey(page, f"perceive{state.get('steps', 0)}", run_dir=c.get("run_dir"))

    # Snapshot form — stored in state so advance_node can check controls
    form = deps.snapshot(page)
    # A kept apply modal with no fields and no way on, before this walk filled ONE field, is
    # the site itself refusing: the walker's own advance click is what opens it (himalayas
    # 'Apply to Upstart', live 2026-10-20 — the reach-level check cannot see a modal that did
    # not exist yet, so the walk burned steps at 0 filled and died no_form_found). Stop and
    # quote the site's words. A walk that already filled something is a modal mid-form, never
    # a refusal; firing stops the walk here, so it can never fire twice.
    if not (state.get("decisions") or []):
        from ..browser.page_prep import _kept_modal_refusal, announce_site_refusal, trail_note
        _refused = _kept_modal_refusal(page)
        if _refused:
            trail_note(step="site_refused", modal=_refused["head"][:60], quote=_refused["quote"][:160])
            return announce_site_refusal(page)      # stopped_reason + site_said: the walk ends here
    from ..orchestrator.advance import screen_signature
    sig = screen_signature(deps.url(page), form)
    return {"form": [_f2d(f) for f in form], "form_sig": sig, "pending_human": [],
            "gate_notice": _submit_gate_notice}


def fill_node(state: AgentState, config) -> dict:
    """Recall → rules → judge; apply confident answers; flag the rest."""
    if state.get("stopped_reason"):
        return {}
    if state["steps"] >= state["max_steps"]:
        return {"stopped_reason": "max_steps"}
    c = config["configurable"]
    page = c["page"]
    deps = c["deps"]

    form = [_d2f(d) for d in state["form"]]
    fillable = [f for f in form if f.kind != "button"]
    # Bank / ID details never flow through the agent: a required one ends the run
    # for the human to fill; optional ones are skipped (orchestrator/sensitive.py).
    from .sensitive import split_sensitive
    fillable, blocked = split_sensitive(fillable)
    if any(f.required for f in blocked):
        print(f"[fill] stopping: form requires bank/ID details {[f.label for f in blocked if f.required]}", flush=True)
        return {"stopped_reason": "sensitive_field", "pending_human": [_f2d(f) for f in blocked if f.required]}
    # Shared ladder (question bank → rules → judge) — also used by boards/;
    # it records every field to the QA recorder itself.
    from .answering import answer_fields
    decisions, needs = answer_fields(fillable, {**c, "page_index": state.get("steps", 0)})

    # a résumé "Select file" button with no file input in the DOM: upload through the native chooser
    pdf = c.get("resume_pdf")
    if pdf and not any(d.action in ("upload", "upload_chooser") for d in decisions) \
            and not any(f.kind == "file" for f in fillable):
        btn = next((f for f in fillable if f.kind == "button" and re.match(r"(select|choose|upload|attach|browse)\b.*\b(file|resume|cv)\b", f.label or "", re.I)), None)
        if btn is None:
            btn = next((f for f in form if f.kind == "button" and re.match(r"(select|choose|upload|attach|browse)\b.*\b(file|resume|cv)\b", f.label or "", re.I)), None)
        if btn:
            from .mapper import FillDecision
            d = FillDecision(btn.ref, "button", btn.label, pdf, "upload_chooser", "resume")
            deps.fill(page, [d])
            page.wait_for_timeout(2500)          # the site may parse the résumé and prefill fields: fill AFTER it
            decisions = decisions + [d]
            print(f"[fill] uploaded résumé through the file chooser ({btn.label!r})", flush=True)

    # Uploads first (a site may parse the résumé and prefill fields), then every other answer top-down.
    uploads = [d for d in decisions if d.action in ("upload", "upload_chooser")]
    rest = [d for d in decisions if d not in uploads]
    done_uploads = [d for d in uploads if d.action == "upload"]
    if done_uploads:
        deps.fill(page, done_uploads)

    # Taleo/ATS two-step attachment widgets: after set_input_files, click "Attach"
    # to commit the file to the table, then mark it as Resume/CV.
    if any(d.action == "upload" for d in decisions):
        try:
            page.wait_for_timeout(500)
            page.get_by_role("button", name=re.compile(r"^attach$", re.I)).first.click(timeout=3000)
            page.wait_for_timeout(800)
            # Taleo may show "This file has already been attached. Overwrite it?"
            # Click No via JS — bypasses Playwright locator/role-match issues with
            # Taleo's <input type="button" value="No"> modal elements.
            try:
                _modal_dismissed = page.evaluate("""() => {
                    if (!document.body.innerText.includes('already been attached')) return false;
                    for (const el of document.querySelectorAll(
                            'input[type=button], input[type=submit], button')) {
                        const v = (el.value || el.textContent || '').trim();
                        if (/^no$/i.test(v)) { el.click(); return true; }
                    }
                    return false;
                }""")
            except Exception:
                _modal_dismissed = False
            if _modal_dismissed:
                print("[fill] dismissed 'already attached' modal", flush=True)
                # Wait for modal to fully leave the DOM
                try:
                    page.wait_for_function(
                        "() => !document.body.innerText.includes('already been attached')",
                        timeout=3000)
                except Exception:
                    page.wait_for_timeout(800)
            # Wait for AJAX partial refresh to complete before anything else touches the page
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                page.wait_for_timeout(1500)
            print("[fill] clicked Attach button after file upload", flush=True)
            # Mark the newly-attached file as the Resume/CV (Taleo table checkbox/radio)
            try:
                page.locator("table").locator("input[type=checkbox],input[type=radio]").first.check(timeout=2000)
            except Exception:
                pass
        except Exception:
            pass

    # Everything else: from the top, one blank after the other; the form is re-read whenever an answer reveals more.
    from .top_down import fill_top_down
    try:
        live = deps.snapshot(page, scroll=False)      # the step's first read already scrolled the whole page
    except Exception:
        live = fillable
    applied, needs = fill_top_down(page, deps, live, rest, needs, {**c, "page_index": state.get("steps", 0)},
                                   skip_prefilled=bool(uploads))
    decisions = uploads + applied
    # A field nothing could answer but the page now holds a value in (the site parsed the résumé into it — checked
    # AFTER the uploads and fills, which is when that happens) is not a question for the human.
    from ..browser.filler import has_value
    kept = [f for f in needs if has_value(page, f)]
    if kept:
        print(f"[fill] already filled on the page, not asked: {[' '.join(f.label.split())[:30] for f in kept]}", flush=True)
        needs = [f for f in needs if f not in kept]

    print(f"[fill] step {state['steps']+1}: {len(decisions)} filled, "
          f"{len(needs)} escalated", flush=True)
    if c.get("run_dir"):                              # the filled page replaces the pre-fill survey shot
        from ..browser.page_shot import capture_page
        capture_page(page, str(__import__("pathlib").Path(c["run_dir"]) / f"perceive{state['steps']}"))

    return {
        "steps": state["steps"] + 1,
        "decisions": (state.get("decisions") or []) + [_dec2d(d) for d in decisions],
        "pending_human": [_f2d(f) for f in needs],
    }


def human_gate_node(state: AgentState, config) -> dict:
    """Interrupt for human input; apply answers to page on resume."""
    fields = [_d2f(d) for d in state["pending_human"]]
    # interrupt() suspends the graph; outer loop collects answers and resumes
    # via graph.invoke(Command(resume=answers), config=same_config)
    answers: dict = interrupt({"fields": [_f2d(f) for f in fields]})
    print(f"[human] got {len(answers or {})} answer(s) — applying", flush=True)   # progress for the stall watchdog and the log

    c = config["configurable"]
    page = c["page"]
    deps = c["deps"]

    from ..orchestrator.screen_review import apply_answers
    new_decisions = apply_answers(fields, answers)
    deps.fill(page, new_decisions)
    from .answering import record_answers
    record_answers(fields, answers, c)

    return {
        "pending_human": [],
        "decisions": (state.get("decisions") or []) + [_dec2d(d) for d in new_decisions],
    }


def _validation_refill(page, deps, failing, c, state) -> dict:
    """The site answered our click with field errors: answer those fields once more — the bank
    re-recalled, prior values re-typed with real keystrokes (React drops programmatic fills) —
    and hand what still fails to the human, quoting the site's own message in the question."""
    ctx = {**c, "page_index": state.get("steps", 0)}
    from ..browser.validation import read_errors
    from ..browser.filler import has_value
    from .answering import answer_fields
    from .mapper import FillDecision, _action_for_kind
    from .top_down import fill_top_down

    live = deps.snapshot(page, scroll=False)
    present = {f.ref: f for f in live}
    # only fields still on the page — the site may have dropped a step or answered a box
    # for itself while we were away
    fields = []
    for f in failing:
        lf = present.get(f.ref)
        if lf is None or lf.kind == "button":
            continue
        fields.append(lf)
    # a value the site filled for itself is not ours to fix
    from ..browser.filler import has_value
    fields = [f for f in fields
              if not (has_value(page, f) and f.kind not in ("combobox", "select", "radio_group", "checkbox_group"))]
    if not fields:
        return {}
    print(f"[advance] the site rejected: {[f.label for f in fields]} — one refill round", flush=True)
    decs, needs = answer_fields(fields, ctx)

    # a field we already decided but the site now rejects: send the SAME answer again,
    # this time with real keystrokes (the answer itself is not the problem — the fill was)
    prior = {d.get("ref"): d for d in (state.get("decisions") or [])}
    for f in fields:
        pd = prior.get(f.ref)
        if not pd or pd.get("value") in (None, ""):
            continue
        needs = [n for n in needs if n.ref != f.ref]
        decs = [d for d in decs if d.ref != f.ref]
        decs.append(FillDecision(ref=f.ref, kind=f.kind, label=f.label, value=pd.get("value"),
                                 action=pd.get("action") or _action_for_kind(f.kind),
                                 source="revalidate"))

    live2 = deps.snapshot(page, scroll=False)
    applied, needs = fill_top_down(page, deps, live2, decs, needs, ctx, skip_prefilled=False)
    decs = list(decs) + list(applied)

    # what still fails after this one round?
    live3 = deps.snapshot(page, scroll=False)
    still, _ = failing_fields(read_errors(page), live3)
    wanted = {f.ref for f in fields}
    still = [f for f in still if f.ref in wanted]
    out = {"decisions": (state.get("decisions") or []) + [_dec2d(d) for d in decs]}
    if still:
        print(f"[advance] still failing after the refill: {[f.label for f in still]}", flush=True)
        out["pending_human"] = [_f2d(f) for f in still]
    return out


def advance_node(state: AgentState, config) -> dict:
    """Click Next or Submit; detect stuck; route back for more screens."""
    if state.get("stopped_reason"):
        return {}
    c = config["configurable"]
    page = c["page"]
    deps = c["deps"]
    human = c["human"]
    learn = c.get("learn")
    assist = c.get("assist")

    def _recovered(reason: str):
        """Claude-assist took an action at a dead end -> re-snapshot and keep going (else None = give up)."""
        if not (assist and assist.recover(page, reason)):
            return None
        nf = deps.snapshot(page)
        from ..browser.validation import progress_signature
        return {"form": [_f2d(f) for f in nf], "form_sig": screen_signature(deps.url(page), nf, progress_signature(page)),
                "url": page.url}

    form = [_d2f(d) for d in state["form"]]
    from ..orchestrator.advance import (
        has_control, pick_advance_label, screen_signature, changed,
        ADVANCE_NAMES, SUBMIT_NAMES, advance_names, entry_apply_label, submit_seen,
    )
    from ..browser.page_prep import untick_opt_ins, visible_clickable_names
    untick_opt_ins(page)                                  # applying is not consent to be mailed (board path does this too)
    has_advance = has_control(form, advance_names(form))
    has_submit = has_control(form, SUBMIT_NAMES)
    entry = None
    if has_submit and not has_advance:
        entry = entry_apply_label(form, state.get("decisions"), visible_clickable_names(page))
    if entry:                                             # a job page's Apply: open the form, then perceive it
        print(f"[advance] nothing filled yet: {entry!r} opens the form, not a submit", flush=True)
        has_submit = False

    if state.get("steps", 0) >= 4 and not state.get("decisions") and not has_submit:
        # Four screens in, not one field filled or asked, and no Submit in sight: this is not an application form (a dead
        # link that landed on a listing page, a search page...). Stop here; do not click on through the site.
        print("[stop] four steps and no form field found — not an application form", flush=True)
        return {"stopped_reason": "no_form_found"}

    if not has_advance and has_submit and submit_seen(form):
        if not state.get("decisions") and not submit_seen(form):
            # Nothing filled and the only 'submit' is an Apply that opens nothing: not a form, not ready for review
            print("[stop] nothing filled and no submit control — not an application form", flush=True)
            return {"stopped_reason": "no_form_found"}
        policy = c.get("autosubmit_policy")
        verdict = policy(page.url, state.get("decisions") or []) if policy else None
        policy_allows = bool(verdict and verdict["allow"])
        if not state["do_submit"] and not policy_allows:
            return {"stopped_reason": "reached_submit_dry_run"}
        # Pre-submit gate re-check
        from ..browser.gate_probe import HANDLERS
        _INTERACTIVE = {"recaptcha_v2_checkbox", "recaptcha_v2_image",
                        "hcaptcha_checkbox", "hcaptcha_image"}
        pre_gate = deps.gate(page)
        if HANDLERS.get(pre_gate, "escalate") != "proceed":
            on_link = _gate_sender(c) or (lambda u: None)
            _notifier = c.get("remote_solve_notifier")
            if pre_gate in _INTERACTIVE and human.remote_solve(
                    page, pre_gate, on_link,
                    **({"notifier": _notifier} if _notifier is not None else {})):
                if HANDLERS.get(deps.gate(page), "escalate") != "proceed":
                    return {"stopped_reason": f"gate:{pre_gate}"}
            else:
                return {"stopped_reason": f"gate:{pre_gate}"}
        has_likely = any(d.get("source") == "qbank_likely" for d in (state.get("decisions") or []))
        autonomous_ok = (state["autonomous"] and not has_likely) or policy_allows
        how = "auto" if autonomous_ok else "tap"
        msg = "Ready to submit (contains best-guess answers — check them)" if has_likely else "Ready to submit"
        if not (autonomous_ok or human.approve(msg)):
            return {"stopped_reason": "submit_declined"}
        if learn and hasattr(deps, "read_back"):
            all_dec = [_d2dec(d) for d in (state.get("decisions") or [])]
            try:
                finals = deps.read_back(page, all_dec)
                learn.record_corrections(form, all_dec, finals)
                if c.get("qa"):     # the agent-controlled submit is the one automatic outcome signal
                    for d in all_dec:
                        fin = finals.get(d.ref)
                        if fin is not None and d.value is not None and d.action in ("fill", "select", "combobox"):
                            c["qa"].outcome(d.ref, "kept" if str(fin).strip() == str(d.value).strip() else "edited")
            except Exception:
                pass
        try:
            from ..browser.form_values import read_form_values
            before_submit = read_form_values(page)                    # what the form holds as it goes out
        except Exception:
            before_submit = {}
        deps.click(page, pick_advance_label(form, is_last=True))
        ok, why = deps.confirmed(page) if hasattr(deps, "confirmed") else (True, "unchecked")
        print(f"[submit] {'CONFIRMED' if ok else 'NOT confirmed'}: {why}", flush=True)
        if not ok:
            return {"submitted": False, "stopped_reason": "submit_unconfirmed"}     # clicked, no proof: a human checks
        if c.get("on_submit"):
            c["on_submit"](before_submit, how, page.url)
        return {"submitted": True, "stopped_reason": "submitted"}

    if not has_advance and not entry:
        # File upload may have just enabled a previously-disabled advance button.
        # Re-snapshot once before giving up.
        page.wait_for_timeout(1500)
        form = deps.snapshot(page, scroll=False)
        has_advance = has_control(form, advance_names(form))
        has_submit = has_control(form, SUBMIT_NAMES)
        if not has_advance and not has_submit and not state.get("decisions"):
            # Nothing applied to a form field and the snapshot shows no advance/submit: a job-description page whose
            # visible 'Apply Now' link opens the form (insyncanalytics, live 2026-10-18: stopped 'no_advance_control').
            from ..browser.page_prep import find_apply_affordance
            aff = find_apply_affordance(page)
            if aff is not None:
                print(f"[advance] nothing applied yet: visible {aff['name']!r} opens the form", flush=True)
                entry = aff["name"]
        if not has_advance and not has_submit and not entry:
            return _recovered("no_advance_control") or {"stopped_reason": "no_advance_control"}
        if has_submit and not has_advance:
            if not state.get("decisions") and not submit_seen(form):
                return {"stopped_reason": "no_form_found"}
            if submit_seen(form):
                if not state["do_submit"]:
                    return {"stopped_reason": "reached_submit_dry_run"}
            # only the 'Apply' family matched with fields already filled: it opens/advances
            # the form, it does not send one — click through below instead of claiming a submit

    deps.click(page, entry or pick_advance_label(form, is_last=False))
    if page.url.startswith("chrome-error://"):
        # The connection dropped as the page went (live Koch 2026-10-19: ERR_INTERNET_DISCONNECTED after a full page):
        # wait for the network, step back to the form; the next pass re-reads and re-fills what the back lost.
        print("[advance] network error page — waiting for the connection, then back to the form", flush=True)
        import urllib.request
        for _ in range(24):
            try:
                urllib.request.urlopen("https://www.google.com/generate_204", timeout=5)
                break
            except Exception:
                page.wait_for_timeout(5000)
        try:
            page.go_back(wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        return {"form": [_f2d(f) for f in deps.snapshot(page)], "url": page.url}

    # Mid-walk credential wall (e.g. iCIMS "Create a login" on screen 2).
    from ..browser.page_prep import classify_entry, clear_auth_wall
    _kind = classify_entry(page)
    if _kind in ("password", "email_auth"):
        _job_url = state.get("url") or page.url
        _adv_prof = c.get("profile")
        _adv_email = _adv_prof.contact.get("email", "") if _adv_prof and hasattr(_adv_prof, "contact") else ""
        from ..browser.credential_provider import provide as _provide
        _adv_phone = _adv_prof.contact.get("phone", "") if _adv_prof and hasattr(_adv_prof, "contact") else ""
        _prov = lambda pg, gate, site: _provide(pg, gate, site, original_url=_job_url, email=_adv_email, phone=_adv_phone)
        print(f"[cred] {_kind} wall mid-walk — credential provider...", flush=True)
        clear_auth_wall(page, credential_provider=_prov)
        from ..browser.page_prep import is_application_form
        # A sign-up that IS a form (name, email, phone... plus a password: Deloitte/Avature 'Register', live 2026-10-18)
        # is the filler's next screen, not a wall: the credentials are already in, the rest is filled like any form.
        if classify_entry(page) in ("password", "email_auth") and not is_application_form(page):
            return {"stopped_reason": "auth_wall"}

    new_form = deps.snapshot(page)
    from ..browser.validation import failing_fields, progress_signature, read_errors, ref_key
    after = screen_signature(deps.url(page), new_form, progress_signature(page))
    errs = read_errors(page)
    if errs:
        shown = "; ".join(dict.fromkeys(e["message"] for e in errs if e["message"]))[:240]
        print(f"[advance] the site says: {shown or '(invalid fields, no messages)'}", flush=True)
    if state.get("form_sig") and not changed(state["form_sig"], after):
        # The page did not move. The site has the floor: bind its complaints to fields and
        # refill those once (MetLife's phone code, Koch's Education/Current?, Workday's loops
        # all stalled here yesterday with the red text unread).
        fail, _banners = failing_fields(errs, new_form)
        done = list(state.get("refilled") or [])
        if fail and ref_key(after) not in done:
            upd = _validation_refill(page, deps, fail, c, state)
            if upd:
                upd.setdefault("form", [_f2d(f) for f in new_form])
                upd["form_sig"] = after
                upd["url"] = page.url
                upd["refilled"] = done + [ref_key(after)]
                return upd
        print("[stop] the page did not change — stuck", flush=True)
        return _recovered("stuck") or {"stopped_reason": "stuck"}
    return {"form": [_f2d(f) for f in new_form], "form_sig": after, "url": page.url}


# ── Routing ───────────────────────────────────────────────────────────────────

def _route_reach(state: AgentState) -> str:
    # Route to cred_provide on first password or email_auth wall (guard prevents loop)
    if state["kind"] in ("password", "email_auth") and not state.get("cred_provided"):
        return "cred_provide"
    return "perceive"


def _route_classify(state: AgentState) -> str:
    k = state["kind"]
    if k == "closed":
        return END
    if k in ("password", "email_auth"):
        return "cred_provide"
    return "tailor_cv"


def _route_perceive(state: AgentState) -> str:
    return END if state.get("stopped_reason") else "fill"


def _route_fill(state: AgentState) -> str:
    if state.get("stopped_reason"):
        return END
    return "human_gate" if state.get("pending_human") else "advance"


def _route_advance(state: AgentState) -> str:
    if state.get("stopped_reason") or state.get("submitted"):
        return END
    if state.get("pending_human"):
        # the validation refill found fields it cannot answer — ask the person,
        # quoting the site's own message, then advance again
        return "human_gate"
    return "perceive"


# ── Build ─────────────────────────────────────────────────────────────────────

def build_graph(checkpointer=None):
    """Return a compiled graph, optionally with a SqliteSaver checkpointer."""
    g = StateGraph(AgentState)
    g.add_node("classify", classify_node)
    g.add_node("cred_provide", cred_provide_node)
    g.add_node("reach", reach_node)
    g.add_node("tailor_cv", tailor_cv_node)
    g.add_node("perceive", perceive_node)
    g.add_node("fill", fill_node)
    g.add_node("human_gate", human_gate_node)
    g.add_node("advance", advance_node)

    g.set_entry_point("classify")
    g.add_conditional_edges("classify", _route_classify,
                            {"cred_provide": "cred_provide", "tailor_cv": "tailor_cv", END: END})
    g.add_edge("cred_provide", "tailor_cv")
    g.add_edge("tailor_cv", "reach")
    g.add_conditional_edges("reach", _route_reach, {"cred_provide": "cred_provide", "perceive": "perceive"})
    g.add_conditional_edges("perceive", _route_perceive, {"fill": "fill", END: END})
    g.add_conditional_edges("fill", _route_fill,
                            {"human_gate": "human_gate", "advance": "advance", END: END})
    g.add_edge("human_gate", "advance")
    g.add_conditional_edges("advance", _route_advance,
                            {"perceive": "perceive", "human_gate": "human_gate", END: END})

    return g.compile(checkpointer=checkpointer)
