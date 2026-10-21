"""Reusable page-prep tools: clear overlays/noise and get the walk to the real
application form. DOM tools are idempotent and never click a submit/destructive
control; suppress_noise is pure. LLM-free."""
from __future__ import annotations

import re
from collections import Counter

# Fields that are never real application inputs.
_NOISE_RE = re.compile(
    r"oda-|ask me something|add summary|work-summary|honey.?pot|"
    r"g-recaptcha-response|h-captcha-response|"
    r"vendor-search-handler|"           # SR city autocomplete sub-widget
    r"upload.profile.image",            # SR avatar photo uploader — not a document upload
    re.I)


def suppress_noise(fields):
    """Drop chatbot (Oracle ODA), honeypot, and captcha-token fields from the
    Form Model. Matches on ref OR label; never drops a field with a known
    purpose."""
    out = []
    for f in fields:
        if f.purpose:
            out.append(f); continue
        if _NOISE_RE.search(f"{f.ref} {f.label}"):
            continue
        out.append(f)
    return out


# Prefer the privacy-preserving option; fall back to accepting if needed to unblock.
# Ordered most-specific first so "Reject all" beats "Reject" etc.
_DECLINE = [
    "Reject all", "Decline all", "Decline all cookies", "Reject all cookies",
    "Reject optional cookies", "Reject optional", "Decline optional cookies", "Reject non-essential",
    "Use necessary cookies only", "Necessary cookies only", "Only necessary cookies",
    "Only essential", "Essential only",
    "Decline", "Reject", "Only necessary", "Necessary only", "Refuse",
]
_ACCEPT = [
    "Allow all cookies", "Accept all cookies", "Accept all",
    "Allow all", "Allow cookies", "Accept cookies",
    "Accept", "Agree", "Allow", "OK", "Got it", "I understand",
    "I agree", "I accept",
]
_JOB_TITLE: str = ""   # ponytail: module-global like _TRAIL; one apply run per process. Set by apply.py before reach.
_TRAIL: list = []   # ponytail: module-global; one apply run per process. Per-run object if runs ever share a process.


def trail_note(**ev) -> None:
    """Record one reach step (hop, modal kept/dismissed, ...) for the run's pending-memory entry."""
    _TRAIL.append(ev)


def take_trail() -> list:
    t = list(_TRAIL)
    _TRAIL.clear()
    return t


def _bare(url: str) -> str:
    """host/path only — query strings carry tracking ids, never stored."""
    from urllib.parse import urlparse
    u = urlparse(url or "")
    return f"{u.netloc}{u.path}"[:90]


_DIALOG_DISMISS = ["Continue Working", "Continue", "Stay", "Stay signed in", "Dismiss", "Close"]
_IDLE_DIALOG_RE = re.compile(r"session|timed? ?out|inactiv|idle|still (there|working|here)|are you there"
                             r"|stay signed in|continue working|about to expire|log(ged)? out", re.I)

# Marketing-upsell modals (job 31867's "don't let your application get lost in the pile" AI
# pitch): the right move is a dismissal affordance, never the primary buy button.
_UPSELL_RE = re.compile(
    r"generate (a )?(cover letter|resume)|ai (cover letter|writer)|premium|boost|upgrade|"
    r"credits?|unlock|don'?t let your application", re.I)

# Their close affordances, in click order. "Continue" is deliberately absent: on an
# upsell that is the sell, not the exit.
_UPSELL_CLOSE = ["No thanks", "No thank you", "Skip for now", "Skip", "Maybe later",
                 "Not now", "Dismiss", "Cancel", "Close"]

# The site's own apply handoff ("I'm ready to apply" on 31867): only the modal's sole
# named control may be clicked as the LAST rung, and never when the modal markup
# carries ad machinery — an ad unit's Apply is not the site's handoff.
_HANDOFF_RE = re.compile(
    r"(?:i'?m |im )?(?:ready|here) to apply|apply (?:now|on |to |for )"
    r"|start (?:the |my |this |an )?(?:application|apply)|begin (?:the |my |a )?application", re.I)
_AD_DIALOG_CSS = "ins.adsbygoogle,[id^=div-gpt-ad],[data-ad-slot],[data-google-av-attrs]"
_CLOSE_X_CSS = ('[aria-label="Close" i],[aria-label="Dismiss" i],[title="Close" i],'
                '[title="Dismiss" i],button:text-is("×"),button:text-is("✕"),button:text-is("⨯")')

# Failed attempts per modal snapshot (page.url + trimmed dialog text). Module-global
# like _TRAIL: one apply run per process; entries clear when the modal resolves.
_MODAL_ATTEMPTS: dict = {}
_STUCK_NOTED: set = set()


def _click_close_x(page, dialog):
    """The icon-only close (×) an upsell offers when no named exit exists."""
    try:
        btn = dialog.locator(_CLOSE_X_CSS).first
        if btn.count() == 0:
            return None
        from .clicks import act
        act(page, lambda: btn.click(timeout=3000), max_wait_ms=3000)
        return "close ×"
    except Exception:
        return None


def _press_escape(page) -> bool:
    """Escape as the last dismissal rung: modals without an explicit close mostly honor it."""
    try:
        from .clicks import act
        act(page, lambda: page.keyboard.press("Escape"), max_wait_ms=2000)
        return True
    except Exception:
        return False


def _click_handoff(page, dialog, names):
    """Final rung, tried once per modal snapshot: the ONLY named control is the
    site's own continue-style handoff ("I'm ready to apply" skipped the upsell and
    opened the form on 31867). An ad-marked dialog is never a handoff — its Apply
    is the ad's — so that closes via Escape instead."""
    controls = [" ".join(n.split()) for n in names if n.strip()]
    if len(controls) != 1 or len(controls[0]) > 80 or not _HANDOFF_RE.search(controls[0].lower()):
        return None
    try:
        ad_marked = dialog.locator(_AD_DIALOG_CSS).count() > 0
    except Exception:
        ad_marked = False
    from .cta_arbiter import is_ad_like
    if is_ad_like({"name": controls[0], "attrs": "advert" if ad_marked else ""}):
        return None
    return _click_first(page, [controls[0]], within=dialog)


def _note_stuck(sig):
    """Mark the 2-strike degrade. Contract note: prepare() discards dismiss_dialogs'
    bool today and no stopped-reason channel exists without touching the walk
    engines, so the degrade shows up as attempts stopping plus this trail/print pair."""
    if sig in _STUCK_NOTED:
        return
    _STUCK_NOTED.add(sig)
    trail_note(step="modal_stuck", attempts=2, url=_bare(sig.split("|", 1)[0]))
    print("[prep] modal stuck: identical snapshot survived 2 attempts — attempts stopped", flush=True)


def _survived(page, sig, strikes):
    """Strike bookkeeping: an attempt counts only when the SAME snapshot (url plus
    trimmed visible text) is still on screen after the click. Two surviving
    snapshots in a row stop all further attempts for that signature."""
    text = ""
    try:
        d = page.locator("[role=dialog]:visible, [role=alertdialog]:visible").first
        if d.count() > 0:
            text = d.inner_text(timeout=1000)
    except Exception:
        text = ""
    if not text or f"{page.url}|{' '.join(text.split())[:400]}" != sig:
        _MODAL_ATTEMPTS.pop(sig, None)     # resolved or re-rendered: no streak carries over
        return
    n = _MODAL_ATTEMPTS[sig] = strikes + 1
    if n >= 2:
        _note_stuck(sig)


def dismiss_dialogs(page) -> bool:
    """Dismiss an idle/blocking modal (e.g. Oracle 'Continue Working'). Never a destructive/submit control, and
    never a button OUTSIDE the modal: a page that merely carries a (hidden) dialog element has its own "Continue"
    that advances the form, and clicking that here skipped a whole step (Indeed's questions page).

    Marketing upsells get a ladder before the old rules: dismiss with the affordance
    they offer ("No thanks"/close ×; Escape last); their primary CTA is never clicked,
    except the site's own apply handoff when it is the modal's ONLY named control and
    the markup shows no ad machinery — clicked once per snapshot, as the last rung.
    The 2-strike rule ends the old six-in-a-row modal loop: the same snapshot gets
    two attempts total, then this stops attempting and records modal_stuck."""
    try:
        dialog = page.locator("[role=dialog]:visible, [role=alertdialog]:visible").first
        if dialog.count() == 0:
            return False
        # [role=button]/[role=link] matter: design-system CTAs are often not <button> (Himalayas
        # 2026-10-20 — the "Apply to X" modal's only apply control was a role=button div, the keep
        # check missed it, Close fired, and the walker re-clicked Apply in a loop forever).
        names = dialog.locator("a[href], button, [role=button], [role=link]").all_inner_texts()
        try:
            text = dialog.inner_text(timeout=1000)
        except Exception:
            text = ""
        fillable = dialog.locator("textarea:visible, select:visible, input:visible:not([type=hidden]):not([type=checkbox])"
                                  ":not([type=radio]):not([type=submit]):not([type=button])").count() > 0
    except Exception:
        return False
    # Where a modal that offers an Apply step sits in the ladder: the upsell archetype
    # dismisses it, a sole continue-CTA handoff is clicked ONCE (an apply-boundary modal
    # is the site's handoff, never an ad unit), anything else keeps today's rules (kept
    # for the drill to click); the 2-strike line comes first — before any dismiss attempt
    # this run already knows this exact snapshot never answers.
    sig = f"{page.url}|{' '.join(text.split())[:400]}"
    strikes = _MODAL_ATTEMPTS.get(sig, 0)
    if strikes >= 2:
        _note_stuck(sig)                       # the degrade: never a third attempt, never a sixth
        return False
    upsell = not fillable and bool(_UPSELL_RE.search(text))
    degraded = strikes >= 1                    # this snapshot survived one dismiss attempt already
    if upsell:
        via = _click_first(page, _UPSELL_CLOSE, within=dialog)
        if not via:
            via = _click_close_x(page, dialog)
        if via:
            trail_note(step="modal_dismissed", via=via, upsell=True)
        elif strikes == 0:
            via = _click_handoff(page, dialog, names)
            if via:
                trail_note(step="modal_advanced", via=via)
        if not via and _press_escape(page):
            via = "Escape"
            trail_note(step="modal_dismissed", via=via, upsell=True)
        _survived(page, sig, strikes)
        return via is not None
    if not degraded and _best_apply([{"name": " ".join(n.split())} for n in names]) is not None:
        hand = None if fillable else _click_handoff(page, dialog, names)   # the (b) sole-continue rung
        if hand:
            trail_note(step="modal_advanced", via=hand)
            _survived(page, sig, strikes)
            return True
        trail_note(step="modal_kept", why="offers an apply control")
        return False
    # A dialog whose HEADER reads like an apply continuation ("Apply to NVIDIA", "Start your
    # application") is the next hop by definition: its Close never fires unconditionally. This
    # keep is reached only when the widened scan above couldn't find the apply control, and it
    # is the merged half of the stack's modal rule (real T&C dialogs never carry this wording).
    if _APPLY_MODAL_RE.search(text):
        trail_note(step="modal_kept", why="the modal IS the apply step")
        return False
    # An application form is often itself a dialog (Work at a Startup, Wellfound): its
    # "Close"/"Continue" would close or advance the application under the agent.
    if fillable and not _IDLE_DIALOG_RE.search(text):
        return False
    via = None
    if degraded:                               # a failing modal deepens its rungs once, then stops
        via = _click_first(page, _UPSELL_CLOSE, within=dialog)
        if not via:
            via = _click_close_x(page, dialog)
        if not via and _press_escape(page):
            via = "Escape"
            trail_note(step="modal_dismissed", via=via)
    if not via:
        via = _click_first(page, _DIALOG_DISMISS, within=dialog)
    if via:
        trail_note(step="modal_dismissed", via=via)
    _survived(page, sig, strikes)
    return via is not None


def _name_re(name: str):
    """A control whose name STARTS with `name` as whole words ("Reject" -> "Reject all"). A substring match let
    "OK" hit "C-ook-ies Settings" and open the cookie preference centre instead of closing the banner."""
    return re.compile(r"^\s*" + re.escape(name) + r"(?![a-z0-9])", re.I)


def _click_first(page, names, within=None):
    """Click the first control named like one of `names`. A short name ("OK", "Stay") must match exactly, and a link
    only on its exact name: substring matching once took "Cookies Policy" (c-OK-ies) for "OK" and left the
    application for the cookie-policy page (live Veritech run, 2026-10-12)."""
    root = within or page
    for name in names:
        try:
            btn = root.get_by_role("button", name=_name_re(name)).first
            if btn.count() == 0:
                btn = root.get_by_role("link", name=_name_re(name)).first
            if btn.count() > 0:
                from .clicks import act
                act(page, lambda: btn.click(timeout=3000), max_wait_ms=3000)
                return name
        except Exception:
            pass
    return None


# The page's text plus the text of every open shadow root: consent managers such as Usercentrics draw the whole banner
# inside one (FedEx careers, live 2026-10-18 — the banner covered Apply and the text check never saw it).
_CONSENT_TEXT_JS = """() => {
  const re = /cookie|consent|privacy preferences|we use cookies/i;
  if (re.test((document.body ? document.body.innerText : '').slice(0, 4000))) return true;
  const seen = []; const walk = root => { for (const e of root.querySelectorAll('*')) if (e.shadowRoot) seen.push(e.shadowRoot); };
  walk(document);
  for (let i = 0; i < seen.length && i < 50; i++) {
    const r = seen[i];
    if (re.test((r.textContent || '').slice(0, 4000))) return true;
    walk(r);
  }
  return false;
}"""


def _looks_consent(page) -> bool:
    try:
        return bool(page.evaluate(_CONSENT_TEXT_JS))
    except Exception:
        return False


def dismiss_consent(page) -> bool:
    """Decline a cookie/consent overlay if offered, else OK/Accept to unblock.
    Retries after a short wait so async-loaded banners (Workable, Cookiebot) are caught.
    Site cookie banners ONLY — never an application T&C/attestation."""
    # Two passes: immediate + 1.5s wait for JS-injected banners
    for attempt in range(2):
        if _looks_consent(page):
            if _click_first(page, _DECLINE):
                return True
            if _click_first(page, _ACCEPT):
                return True
        if attempt == 0:
            page.wait_for_timeout(1500)
    return False


# A dialog titled/introduced like an apply continuation ("Apply to NVIDIA", “Start your application”)
# is the next hop by definition: its Close never fires unconditionally. Only consent/idle text
# opt-out; real T&C dialogs never carry this wording.
_APPLY_MODAL_RE = re.compile(r"\bapply (to|now|for|online)\b|\bstart (your|the) application\b|"
                             r"\b(job )?application (form|portal|step)\b", re.I)


# Himalayas 2026-10-20 (live CDP probe): after Apply, the site answers with an "Apply to Upstart"
# modal (~512×440) holding ZERO input/select/textarea elements and no way forward — its only
# clickables are Close, "Update your working permit information" (a→/profile/preferences),
# "Update profile" (a→/profile/preferences) and "Find similar jobs". Walking that formless state
# burned ~110 s, filled 0 of the 4 buttons it perceived as rows, and ended no_form_found. That
# modal is the site itself refusing the application (a profile-preferences nag), so reach must
# stop and escalate, quoting the site's own words. All three must hold before it is called a
# refusal: (a) no real field inside the dialog (invisible hidden-type inputs only), (b) the head
# matches _APPLY_MODAL_RE, (c) none of its clickables names a way on — a no-inputs modal WITH a
# Continue/Submit/Sign-in hand-off opens another surface and keeps the existing modal_kept flow.
_APPLY_REFUSAL_JS = """(applyPat) => {
  const big = e => { const r = e.getBoundingClientRect(); return r.width >= 200 && r.height >= 200; };
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 4 && r.height > 4; };
  const text = e => (e.innerText || '').trim().replace(/\\s+/g, ' ');
  let dlg = null, area = 0;
  for (const d of document.querySelectorAll('[role=dialog],[role=alertdialog]'))
    if (big(d)) {
      const r = d.getBoundingClientRect();
      if (r.width * r.height > area) { dlg = d; area = r.width * r.height; }
    }
  if (!dlg) return null;
  const he = dlg.querySelector('h1, h2, h3');
  const head = ((he && text(he)) || (dlg.getAttribute('aria-label') || '')).replace(/\\s+/g, ' ').trim();
  if (!new RegExp(applyPat, 'i').test(head)) return null;
  // (a) no real fields: a hidden-type box is effectively invisible, anything shown kills it
  if (Array.from(dlg.querySelectorAll('input,select,textarea')).filter(e => vis(e) && e.type !== 'hidden').length) return null;
  // (c) a clickable named like a way on = hands off elsewhere, never a refusal
  const PROCEED = /apply|continue|next|submit|start|sign[\\s-]?in|sign[\\s-]?up|create|register/i;
  if (Array.from(dlg.querySelectorAll('a,button,[role=button]')).filter(vis).some(c => PROCEED.test(text(c)))) return null;
  return { head: head, quote: (dlg.innerText || '').slice(0, 600) };
}"""


def _kept_modal_refusal(page) -> dict | None:
    """The kept apply modal that is not an apply: no fields and no way forward — the site itself
    refusing the application. Returns {"head", "quote"} for the escalation's message, else None
    (a modal WITH a field or a proceed CTA stays on the existing modal_kept / walk flow)."""
    try:
        d = page.evaluate(_APPLY_REFUSAL_JS, _APPLY_MODAL_RE.pattern)
    except Exception:
        return None
    if isinstance(d, dict) and isinstance(d.get("head"), str) and isinstance(d.get("quote"), str) \
            and d["head"] and d["quote"]:
        return d
    return None


def announce_site_refusal(page) -> dict:
    """The one-line [stop] quoting the site's own words, plus the {stopped_reason, site_said} bits
    callers merge into their result dicts (reach boundary in apply.py, walk step in step_engine,
    graph perceive). Always prints — empty quote when the modal already left between the stop
    decision and this read — so the run log names the stall either way."""
    r = _kept_modal_refusal(page) or {}
    head = str(r.get("head") or "")
    said = str(r.get("quote") or "")[:240]
    print(f'[stop] the site itself refuses this application: {head} — "{said}"', flush=True)
    return {"stopped_reason": "site_refused", "site_said": said}


_CLOSED_RE = re.compile(
    r"job (not found|you requested was not found)|no longer available"
    r"|could ?n'?t find anything|posting[^.]{0,40}(closed|removed)|404 error"
    r"|job board[^.]{0,40}no longer active|page not found",
    re.I)


# A banner right under the job title on a full-length page ("Not currently accepting applications"): the posting is
# alive as text but dead as an application. Only the top of the page counts, so a JD that mentions it later does not.
_CLOSED_TOP_RE = re.compile(
    r"(not|no longer|isn'?t|is not)( currently| presently| actively)? accepting (new )?applications?"
    r"|applications? (are |is |have )?(now |been )?(closed|ended)|(job|position|role|vacancy|posting|requisition)"
    r"[^.\n]{0,25}\b(is |has been |was )?(now )?(closed|filled|expired|removed|no longer (open|available|active))\b"
    r"|this job (has )?expired|(job|posting) (has )?expired|(position|role) has been filled", re.I)


def _looks_closed(text: str) -> bool:
    """True if the page is a dead-posting shell (expired/removed/404), or says near its top that applications are
    closed. The whole-body phrases are guarded to a short body so a long JD that merely mentions '404' isn't flagged."""
    t = (text or "").strip()
    if not t:
        return False
    if _CLOSED_TOP_RE.search(t[:2500]):
        return True
    if len(t) > 600:
        return False
    return _CLOSED_RE.search(t) is not None


def is_closed_posting(page) -> bool:
    try:
        return _looks_closed(page.evaluate("() => document.body.innerText"))
    except Exception:
        return False


# An email-first account wall: the password box sits behind a "Sign in with email" control, beside social sign-in
# buttons (Workday; live Hitachi 2026-10-18). Matched on the control's whole text, so the same words inside a long
# form can't make it a wall. Shared by classify_entry (detection) and credential_provider (the click that reveals it).
EMAIL_REVEAL_RE = re.compile(r"^(?:(?:sign ?in|log ?in|sign ?up|register|continue) with (?:e-?mail|email address)"
                             r"|(?:use|continue with) e-?mail)$", re.I)
SOCIAL_SIGNIN_RE = re.compile(r"^(?:sign ?in|log ?in|sign ?up|continue) with (?:apple|google|linkedin|facebook|microsoft|github)$",
                              re.I)


def classify_entry(page, status=None) -> str:
    """Which of the two application shapes (or a JD/password gate) is on screen:
    'closed' | 'form' | 'email_auth' | 'password' | 'none'.

    Reasoning for 'closed': a 404/410 HTTP status is decisive; otherwise it needs
    BOTH no fillable form AND dead-posting language — so a live form is never
    'closed', and a page that's alive but whose form we didn't reach is 'none'
    (a different problem: a second hop / login / render), not 'closed'."""
    if status in (404, 410):
        return "closed"
    # Darwinbox uses shadow-DOM inputs that querySelectorAll can't see;
    # detect its auth pages by URL instead of DOM probing.
    _u = page.url
    if "darwinbox.com/cookie-policy" in _u or "/ms/candidatev2/main/auth/" in _u:
        return "password"
    try:
        d = page.evaluate("""(pats) => {
          const vis = e => { const r=e.getBoundingClientRect(); return r.width>4 && r.height>4; };
          const ctlText = e => (e.innerText || e.value || '').trim().replace(/\\s+/g, ' ');
          const ctls = Array.from(document.querySelectorAll('button,a[href],[role=button],input[type=button],input[type=submit]'))
            .filter(vis).map(ctlText);
          const emailReveal = ctls.some(t => new RegExp(pats[0], 'i').test(t));
          const social = ctls.some(t => new RegExp(pats[1], 'i').test(t));
          const ins = Array.from(document.querySelectorAll('input,select,textarea')).filter(vis);
          const txt = document.body.innerText.slice(0, 4000);
          const hasPw = ins.some(e => e.type === 'password')
                        || /create a password|sign in with password/i.test(txt)
                        || /you do not have access/i.test(txt);
          const hint = e => (e.name||'')+' '+(e.id||'')+' '+(e.getAttribute('aria-label')||'')+' '+(e.placeholder||'')+' '+(e.autocomplete||'');
          const email = ins.find(e => e.type === 'email' || /mail|user|login/i.test(hint(e)));
          const fillable = ins.filter(e => !['hidden','submit','button','password'].includes(e.type)
            && !/search/i.test(e.getAttribute('aria-label')||e.name||'')).length;
          // a sign-in step's own button (IBMid: "Continue"), not a job-alert box's "Subscribe"
          const authBtn = Array.from(document.querySelectorAll('button,input[type=submit],[role=button]')).filter(vis)
            .some(e => /^(continue|next|sign ?in|log ?in|login)$/i.test((e.innerText || e.value || '').trim()));
          return { hasPw, hasEmail: !!email, authBtn, emailReveal, social,
            verify: /verify|one-time|we'll send|continue with email|create .*profile|create (an |your )?account|confirm your identity|start application|begin.*apply|sign.?in|sign.?up|log.?in or|register/i.test(txt),
            fillable };
        }""", [EMAIL_REVEAL_RE.pattern, SOCIAL_SIGNIN_RE.pattern])
    except Exception:
        return "none"
    if d["hasPw"]:
        return "password"
    # Social buttons + "Sign in with email" on a small page: the password gate, one click away (no box shown yet).
    if d.get("emailReveal") and d.get("social") and d["fillable"] <= 4:
        return "password"
    # An email-first gate is a tiny page; a long form that merely mentions "signing"/"sign in" is not.
    from .credential_provider import alert_box_only
    if d["hasEmail"] and (d["verify"] or d["authBtn"]) and d["fillable"] <= 4 and not alert_box_only(page):
        return "email_auth"
    if d["fillable"] >= 2:
        return "form"                       # a form is present -> never 'closed'
    if is_closed_posting(page):             # no form + dead-posting language -> closed
        return "closed"
    return "none"                           # no form, but alive -> unreached, not dead


# --- What a login / sign-up wall looks like -------------------------------

_LOGIN_SIGNALS_JS = r"""() => {
  const vis = e => { const r=e.getBoundingClientRect(); return r.width>4 && r.height>4; };
  const ins = Array.from(document.querySelectorAll('input,select,textarea')).filter(vis);
  const hint = e => ((e.name||'')+' '+(e.id||'')+' '+(e.getAttribute('aria-label')||'')+' '+(e.placeholder||'')+' '+
                     (e.labels && e.labels[0] ? e.labels[0].innerText : ''));
  const ctl = Array.from(document.querySelectorAll('button,a[href],[role=button],input[type=submit]')).filter(vis)
    .map(e => (e.innerText || e.value || '').trim().replace(/\s+/g,' ')).filter(Boolean);
  return {
    hasPassword: ins.some(e => e.type === 'password'),
    hasUser: ins.some(e => ['text','email','tel'].includes(e.type) && /mail|user|login|account/i.test(hint(e))),
    authControl: ctl.some(t => /^(sign ?in|log ?in|login|sign ?up|register|create (an? )?account|forgot( your)? password\??)\b/i.test(t)),
    credInputs: ins.filter(e => !['hidden','submit','button','checkbox','radio','search'].includes(e.type)).length,
  };
}"""


def login_from_signals(d: dict) -> bool:
    """A login / account wall, however the site words it: a password box next to a username/email box or a
    sign-in / create-account / forgot-password control, on a SMALL form (at most 4 inputs). A password box
    inside a long application form is the combined registration+application case, not a wall."""
    return bool(d.get("hasPassword") and (d.get("hasUser") or d.get("authControl")) and d.get("credInputs", 99) <= 4)


def is_login_page(page) -> bool:
    try:
        return login_from_signals(page.evaluate(_LOGIN_SIGNALS_JS))
    except Exception:
        return False


# An auth word standing as its own path segment (not mentioned inside a job slug)
_WALL_WORDS = ("register", "signup", "sign-up", "login", "log-in", "signin",
               "authenticate", "create-account")

# "sign up / log in" still being sold in the site's own chrome — the header/nav is
# how you land on the wall from a logged-out page (mirrors the structural chrome
# skip in credential_provider._is_page_chrome / perception's header skip).
_CHROME_AUTH_JS = r"""() => {
  const vis = e => { const r=e.getBoundingClientRect(); return r.width>4 && r.height>4; };
  return Array.from(document.querySelectorAll('header a, header button, nav a, nav button, [role=banner] a, [role=banner] button'))
    .filter(vis).some(e => /sign ?up|log ?in|sign ?in|register|create (an? )?account/i.test(e.innerText || ''));
}"""


def wallish_url(url) -> bool:
    """Pure: the path itself IS the account wall — an auth word standing as one of
    the first two path segments (instahyre /candidates/register/, job 30076). A job
    slug that merely mentions "register" deeper in the path never trips it."""
    from urllib.parse import urlparse
    try:
        segs = [s for s in (urlparse(url or "").path or "").lower().split("/") if s]
    except ValueError:
        return False
    return any(seg in _WALL_WORDS for seg in segs[:2])


def is_wall(page, url) -> bool:
    """A login / SIGN-UP wall on screen? URL tell first (cheap), then the DOM:
    the password-box crowd (login_from_signals) or an email-first form whose
    header chrome still sells creating an account. Consulted BEFORE perception
    so a register page is never read as the application's fields."""
    try:
        if wallish_url(url):
            return True
        d = page.evaluate(_LOGIN_SIGNALS_JS) or {}
        if isinstance(d, dict) and login_from_signals(d):
            return True
    except Exception:
        return False
    try:
        from .credential_provider import _is_email_first
        return bool(_is_email_first(page)) and bool(page.evaluate(_CHROME_AUTH_JS))
    except Exception:
        return False


# --- Reaching the real application form ----------------------------------
# The URL an external "Apply" link lands on is usually NOT the form: it's a JD
# page, a search/listing page, or a JS-rendered SPA shell, with the form one or
# two clicks in behind an "Apply" affordance. So instead of guessing whether the
# current page "is a form", we DRILL: is the real form here? if not, click the
# Apply affordance and look again — bounded, loop-safe, gates escalate.

# Count of DISTINCT real applicant fields on the page (name/email/resume/phone).
# A search box, filter checkboxes, or a chatbot input score zero — that's what
# separates the application form from a JD/search/SPA landing.
_REAL_FIELDS_JS = r"""() => {
  function shadowAll(root, sel) {
    const r = [];
    function walk(n) {
      try { if (n.matches && n.matches(sel)) r.push(n); } catch(e){}
      if (n.shadowRoot) walk(n.shadowRoot);
      for (const c of (n.children || [])) walk(c);
    }
    walk(root); return r;
  }
  const vis = e => { try { const r=e.getBoundingClientRect(); return r.width>4&&r.height>4; } catch(e){ return false; } };
  // Accessible label text: aria-labelledby (space-separated ids, resolved in the
  // element's own root so it works inside shadow DOM too) beats aria-label, since
  // custom-widget forms (Google Forms among them) label via labelledby only.
  const labelText = e => {
    const ids = (e.getAttribute('aria-labelledby')||'').trim();
    if (!ids) return '';
    const root = e.getRootNode();
    return ids.split(/\s+/).map(id => {
      try { return (root.getElementById ? root.getElementById(id) : document.getElementById(id))?.innerText || ''; }
      catch(e) { return ''; }
    }).join(' ');
  };
  // A site search box or newsletter/subscribe signup is not the application, whatever its labels say.
  const SUB = /newsletter|subscribe|search/i;
  const junkBox = e => e.type === 'search' || !!e.closest('[role=search]') || (() => {
    const f = e.closest('form'); return !!f && SUB.test((f.id||'')+' '+(f.className||'')+' '+(f.getAttribute('action')||'')+' '+(f.getAttribute('aria-label')||'')); })();
  // file inputs are styled invisible (display:none) but are real upload fields
  const ins = shadowAll(document.body, 'input,select,textarea').filter(e =>
    e.type === 'file' || (vis(e) && !junkBox(e)));
  const seen = new Set();
  for (const e of ins) {
    if (['hidden','submit','button'].includes(e.type)) continue;
    const hay = ((e.getAttribute('aria-label')||'')+' '+labelText(e)+' '+(e.name||'')+' '+(e.id||'')
                 +' '+(e.placeholder||'')+' '+(e.type||'')).toLowerCase();
    let k = null;
    if (e.type==='email' || /\be-?mail\b/.test(hay)) k='email';
    else if (e.type==='file' || /resume|\bcv\b|upload/.test(hay)) k='resume';
    else if (/first.?name|last.?name|full.?name|your.?name|given.?name|family.?name|surname/.test(hay)) k='name';
    else if (/phone|mobile/.test(hay) || e.type==='tel') k='phone';
    if (k) seen.add(k);
  }
  return seen.size;
}"""

# Every visible clickable's name + role + a stamped unique ref. We click by the
# ref (element identity), NOT by accessible name — a Phenom "Apply Now" link
# nests an icon, so its accname isn't exactly "Apply Now" and get_by_role(name=)
# times out. data-aff sidesteps that.
_CLICKABLES_JS = r"""() => {
  // A visibility:hidden or opacity:0 control has a box but is not shown: not a control the agent may click.
  const vis = e => { const r=e.getBoundingClientRect(); return r.width>4 && r.height>4
    && (e.checkVisibility ? e.checkVisibility({visibilityProperty:true, opacityProperty:true}) : true); };
  if (window.__affN === undefined) window.__affN = 0;
  const out = [];
  // Controls inside an open modal/dialog come first: a modal is what the page is asking
  // about right now, and it sits at the end of the DOM — past the 200 cap on busy pages.
  const inModal = e => !!e.closest('[role=dialog],[aria-modal=true],dialog[open]');
  const CTRL = 'button, a[href], [role=button], input[type=submit], input[type=button]';
  const applyLike = x => /apply/i.test(x.getAttribute('aria-label') || x.value || x.textContent || '');
  // The job card = the largest ancestor that still holds exactly ONE apply-like control (the nearest ancestor is
  // just the button's wrapper, which lacks the job's title). A listing's cards each hold their own Apply.
  const cardOf = e => {
    let card = '';
    for (let a = e.parentElement, i = 0; a && a !== document.body && i < 12; a = a.parentElement, i++) {
      const n = [...a.querySelectorAll(CTRL)].filter(applyLike).length;
      if (n > 1) break;
      if (n === 1) card = (a.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 400);
    }
    return card;
  };
  const els = [...document.querySelectorAll(CTRL)]
    .filter(vis).sort((a, b) => inModal(b) - inModal(a));
  for (const e of els) {
    const name = (e.getAttribute('aria-label') || e.value || e.textContent || '').trim().replace(/\s+/g,' ');
    if (!name) continue;
    // Stable id: reuse an existing stamp so a control keeps the same ref across
    // scans — lets the drill know it already clicked a dropdown TOGGLE and pick
    // the revealed menu OPTION next, instead of re-toggling.
    let aff = e.getAttribute('data-aff');
    if (!aff) { aff = 'a' + (window.__affN++); e.setAttribute('data-aff', aff); }
    out.push({ name, role: e.tagName === 'A' ? 'link' : 'button', ref: '[data-aff="' + aff + '"]',
               card: applyLike(e) ? cardOf(e) : '' });
  }
  return out.slice(0, 200);
}"""

# Apply affordances, highest-priority phrase first. Anything containing a DENY
# term is rejected even if it also contains "apply" ("Apply filter", "Easy apply").
_AUTH_WALLS = {"password", "email_auth"}    # login / account-creation gates


def is_auth_wall(page) -> bool:
    """True while an account/login wall blocks the application (a password or
    email-verify page). The agent never types the password — it hands off to the
    human and waits for this to go False."""
    return classify_entry(page) in _AUTH_WALLS


def auth_cleared(page) -> bool:
    """Predicate for RemoteSolveSession.wait_until_cleared: the wall is gone (the
    human authenticated), so the drill/walk can resume behind the session."""
    return not is_auth_wall(page)


_TENANT_PARAMS = ("company", "tenant", "org", "orgid", "client", "companyid")


def site_key(url: str) -> str:
    """The key a saved login is filed under: the host, plus the tenant when the URL names one. Multi-company
    hosts (SuccessFactors: career44.sapsf.com?company=birlasoftl) hold a separate account per company, so a
    login saved for one company must not be taken for another's (that skipped sign-up and failed the login)."""
    from urllib.parse import parse_qs, urlparse
    try:
        u = urlparse(url)
        host = (u.hostname or "").lower()
        q = {k.lower(): v for k, v in parse_qs(u.query).items()}
    except Exception:
        return ""
    for k in _TENANT_PARAMS:
        if q.get(k) and q[k][0].strip():
            return f"{host}?{k}={q[k][0].strip().lower()}"
    return host


def _site_of(page) -> str:
    """The key an operator provider uses to generate/look up the right credential for the wall's site."""
    try:
        return site_key(page.url)
    except Exception:
        return ""


def clear_auth_wall(page, credential_provider=None) -> bool:
    """Seam for OPTIONAL operator-supplied auth automation. With no provider (the
    default) this returns False, so the caller does the human hand-off — the agent
    itself never handles credentials. If the operator wired a
    credential_provider(page, gate, site)->bool for accounts THEY own, call it
    (site = the ATS host, so it can pick the right per-site credential) and report
    whether the wall actually cleared. The secret lives entirely in that callable;
    it never enters the agent's context. See browser/credential_provider.py."""
    if credential_provider is None:
        return False
    try:
        credential_provider(page, classify_entry(page), _site_of(page))
    except Exception:
        return False
    return auth_cleared(page)


_APPLY_ALLOW = (
    "i'm ready to apply", "im ready to apply", "ready to apply",   # pre-apply modals (e.g. Himalayas)
    "apply for this job", "apply for this role", "apply to this job",
    "apply now", "apply online", "submit application", "start application",
    "apply", "get started", "i'm interested", "im interested",
)
_APPLY_DENY = (
    "save", "search", "sign in", "sign up", "log in", "login", "register",
    "create account", "filter", "refer", "subscribe", "share", "print",
    "job alert", "view all", "back to", "learn more",
    "apply with",      # blocks "Apply With LinkedIn/Indeed/SEEK/Google" OAuth buttons
    "facebook", "instagram", "youtube", "twitter", "whatsapp", "external link",   # a site's footer social links
)


def _is_ad_frame(url: str, title: str = "", name: str = "") -> bool:
    """True for an advertising iframe: ad-network host (the superset list lives in
    browser/cta_arbiter — one table, shared with the perception frame deny),
    <iframe title="Advertisement">, or an AdSense slot name (aswift_*, google_ads_*).
    Its "Apply Now" is an ad's, not the job's."""
    from .cta_arbiter import is_ad_like
    return is_ad_like({"url": url or "", "frame_title": title or "", "frame_name": name or ""})


# "Autofill with Resume", "Apply with my CV", "Upload your resume to autofill": the site reads the résumé and fills the
# form, so it is always the entry to take over "Apply manually" (and over any learned manual route).
_RESUME_AUTOFILL = re.compile(
    r"\b(auto-?\s?fill|apply|fill|import|populate|pre-?fill)\b.{0,25}\b(with|using|from|via|by)\b.{0,15}\b(my |your |a )?(resume|cv|r[ée]sum[ée])\b"
    r"|\b(upload|attach|add)\b.{0,20}\b(resume|cv|r[ée]sum[ée])\b.{0,25}\bauto-?\s?fill\b", re.I)


def _best_apply(cands, exclude=(), prefer=()):
    """cands: [{'name', 'role', 'ref'?}]. Return the best Apply control
    (highest-priority allow phrase, not denied), skipping any whose ref is in
    `exclude` (already clicked). `prefer`: control names the ATS graph learned for this
    site, in click order — an exact match outranks every phrase (still never a denied
    name). Or None. Pure — the ranking core, unit-tested."""
    prefer = [p.strip().lower() for p in prefer]
    best, best_rank = None, len(_APPLY_ALLOW)
    for c in cands:
        if c.get("ref") in exclude:
            continue
        name = (c.get("name") or "").strip().lower()
        if name and len(name) <= 80 and _RESUME_AUTOFILL.search(name):
            if -10**6 < best_rank:
                best, best_rank = c, -10**6                    # beats every phrase and every learned route
            continue
        if not name or len(name) > 80 or any(d in name for d in _APPLY_DENY):
            continue
        if name in prefer:
            rank = prefer.index(name) - len(prefer)       # negative: beats any phrase; earlier step first
            if rank < best_rank:
                best, best_rank = c, rank
            continue
        for rank, allow in enumerate(_APPLY_ALLOW):
            if allow in name:
                if rank < best_rank:
                    best, best_rank = c, rank
                break
    return best


def _arb_candidate(c, exclude) -> bool:
    """The only candidates worth arbitrating: same accept rules `best_apply`
    applies (an allow phrase, no deny term, usable name, not already clicked)."""
    name = (c.get("name") or "").strip().lower()
    return (bool(name) and len(name) <= 80 and c.get("ref") not in exclude
            and not any(d in name for d in _APPLY_DENY)
            and any(a in name for a in _APPLY_ALLOW))


def _frame_seat(page, fr) -> dict:
    """The owning <iframe>'s descriptors: its attribute tells (src/title/name/id/class)
    plus how it sits in the viewport (banner-sized, or pinned in a top corner band) —
    the sit evidence `cta_arbiter` uses to sink corner ad units below real controls."""
    seat = {"frame_url": fr.url or "", "small_frame": False, "corner_frame": False}
    try:
        el = fr.frame_element()
        seat["attrs"] = f"{el.get_attribute('id') or ''} {el.get_attribute('class') or ''}"
        title, name = el.get_attribute("title") or "", el.get_attribute("name") or ""
        if title:
            seat["frame_title"] = title
        if name:
            seat["frame_name"] = name
        box = el.bounding_box()
        vw = page.viewport_size or {}
        if box and vw.get("width") and vw.get("height"):
            seat["small_frame"] = box["width"] < 420 and box["height"] < 420
            seat["corner_frame"] = ((box["x"] <= 80 or box["x"] + box["width"] >= vw["width"] - 80)
                                    and box["y"] < min(300, vw["height"] * 0.4))
    except Exception:
        pass                                  # detached / cross-origin mid-scan: attribute-less seat
    return seat


def _enrich_sit(page, eligible):
    """Attach the arbiter's sit attributes to each candidate: one cheap JS pass
    per frame that already produced rows (the sticky/footer/ad-container read),
    plus the owning frame's seat. Multi-candidate pages only — the common path
    never pays for this."""
    from .cta_arbiter import SIT_REPORT_JS
    sit, seats = {}, {}
    for idx, fr in enumerate(page.frames):
        here = [c for c in eligible if c.get("frame") == idx]
        if not here:
            continue
        refs = [c.get("ref") for c in here if c.get("ref")]
        try:
            sit.update({r.get("ref", ""): r for r in fr.evaluate(SIT_REPORT_JS, refs) or []
                        if isinstance(r, dict) and r.get("ref")})
        except Exception:
            pass                              # frame closed mid-scan: those candidates stay attribute-less
        if idx:
            seats[idx] = _frame_seat(page, fr)
    out = []
    for c in eligible:
        d = sit.get(c.get("ref") or "", {})
        seat = seats.get(c.get("frame"), {})
        out.append({**c, **{k: d.get(k) for k in ("sticky", "fixed_bottom", "in_footer") if d.get(k)},
                    "attrs": f"{c.get('attrs') or ''} {d.get('ad_mark') or ''} {seat.pop('attrs', '')}".strip(),
                    **seat})
    return out


def _pick_best(page, cands, exclude=(), prefer=()):
    """More than one plausible Apply control on screen? Let the arbiter rank their
    provenance (frame class, position, label) and take the best. Nothing to
    arbitrate — none/single candidate, a learned-route hit or a resume-autofill
    control in play — and the pick is exactly `best_apply`'s, today's rules."""
    best = _best_apply(cands, exclude, prefer)
    prefer = [p.strip().lower() for p in prefer]
    if (best is None
            or any((c.get("name") or "").strip().lower() in prefer for c in cands)
            or any(_RESUME_AUTOFILL.search((c.get("name") or "").strip().lower()) for c in cands)):
        return best
    eligible = [c for c in cands if _arb_candidate(c, exclude)]
    if len(eligible) < 2:
        return best
    try:
        from .cta_arbiter import rank          # pure module: ranks descriptors, never gates behavior
        ranked = rank(_enrich_sit(page, eligible), allow=_APPLY_ALLOW)
    except Exception:
        return best                            # arbiter trouble must never change today's pick
    return ranked[0] if ranked else best
def visible_clickable_names(page):
    """Lowercased names of the controls the page actually shows (same visibility rule as the Apply search), across
    frames. None when the page can't be read. The snapshot also lists hidden buttons; this is the check for them."""
    names = set()
    try:
        for fr in page.frames:
            for row in (fr.evaluate(_CLICKABLES_JS) or []):
                names.add((row.get("name") or "").strip().lower())
    except Exception:
        return None
    return names


def _manual_option_hop(page) -> bool:
    """A choose-how-to-apply page (Avature: 'Choose any option to apply': From Device / Copy & Paste / Without Resume /
    LinkedIn ...) has no form yet. Its manual option ('Without Resume') is the way into the form: click it."""
    from .credential_provider import (_REGISTRATION_OPTIONS, _navigate_to_form, _registration_options_offered,
                                      _start_by_resume_upload)
    if not _registration_options_offered(page, wait_ms=500):   # one look: this runs on every reached page
        return False
    if _navigate_to_form(page, _REGISTRATION_OPTIONS, "manual application option"):
        return True
    # no manual option (Deloitte/MetLife Avature: From Device / Copy & Paste / LinkedIn): the résumé upload starts it
    from urllib.parse import urlparse
    return _start_by_resume_upload(page, urlparse(page.url).netloc)


def _real_field_count(page) -> int:
    total = 0
    for fr in page.frames:                 # include embedded ATS iframes
        try:
            total += int(fr.evaluate(_REAL_FIELDS_JS))
        except Exception:
            pass
    return total


def is_application_form(page) -> bool:
    """True only when >=2 distinct real applicant fields (name/email/resume/phone)
    are present — so a JD/search/SPA landing is never mistaken for the form."""
    return _real_field_count(page) >= 2


# Forward controls of a multi-step application (mirrors orchestrator ADVANCE_NAMES).
# A wizard step has one of these; a JD/search page has "Apply"/"Search" instead.
_ADVANCE_WORDS = ("save and continue", "save & continue", "continue", "next", "review")

# Count of visible, non-search fillable fields (mirrors classify_entry's filter).
_FILLABLE_JS = r"""() => {
  function shadowAll(root, sel) {
    const r = [];
    function walk(n) {
      try { if (n.matches && n.matches(sel)) r.push(n); } catch(e){}
      if (n.shadowRoot) walk(n.shadowRoot);
      for (const c of (n.children || [])) walk(c);
    }
    walk(root); return r;
  }
  const vis = e => { try { const r=e.getBoundingClientRect(); return r.width>4&&r.height>4; } catch(e){ return false; } };
  // A site search box or newsletter/subscribe signup is not the application, whatever its labels say.
  const SUB = /newsletter|subscribe|search/i;
  const junkBox = e => e.type === 'search' || !!e.closest('[role=search]') || (() => {
    const f = e.closest('form'); return !!f && SUB.test((f.id||'')+' '+(f.className||'')+' '+(f.getAttribute('action')||'')+' '+(f.getAttribute('aria-label')||'')); })();
  return shadowAll(document.body, 'input,select,textarea').filter(e => {
    const t = (e.getAttribute('type') || 'text').toLowerCase();
    // file inputs are always styled invisible but are real upload fields — count them regardless
    if (t === 'file') return true;
    if (!vis(e)) return false;
    if (['hidden','submit','button','password'].includes(t)) return false;
    if (junkBox(e)) return false;
    return !/search/i.test((e.getAttribute('aria-label') || e.name || ''));
  }).length;
}"""


def _fillable_count(page) -> int:
    total = 0
    for fr in page.frames:
        try:
            total += int(fr.evaluate(_FILLABLE_JS))
        except Exception:
            pass
    return total


def _has_advance(page) -> bool:
    for fr in page.frames:
        try:
            rows = fr.evaluate(_CLICKABLES_JS)
        except Exception:
            continue
        for c in (rows or []):
            n = (c.get("name") or "").strip().lower()
            if any(n == w or n.startswith(w + " ") for w in _ADVANCE_WORDS):
                return True
    return False


def _is_wizard_step(page) -> bool:
    """A multi-step application screen: >=1 fillable (non-search) field AND a
    forward control (Next/Continue/Review). This catches a wizard whose FIRST
    step is a single screening question (not personal info), which
    is_application_form misses — while a JD/search page (Apply/Search button, no
    Next) is correctly excluded."""
    return _fillable_count(page) >= 1 and _has_advance(page)


def find_apply_affordance(page, exclude=(), prefer=()):
    """The best Apply button/link across all frames, as {'name','role','frame',
    'ref'}, skipping refs in `exclude` (already clicked). `frame` is the index
    into page.frames the control lives in. When more than one plausible Apply
    control is visible the arbiter (browser/cta_arbiter) ranks them; with none/one
    visible the pick stays exactly the phrase rank — no change for clean boards."""
    cands = []
    for idx, fr in enumerate(page.frames):
        if idx and _frame_is_ad(fr):
            continue
        try:
            rows = fr.evaluate(_CLICKABLES_JS)
        except Exception:
            continue
        for c in (rows or []):
            c["frame"] = idx
            cands.append(c)
    return _pick_best(page, cands, exclude, prefer)


def set_job_hint(title: str) -> None:
    """The job being applied for. A listing page (several cards, each with its own Apply) is opened at THIS job's card."""
    global _JOB_TITLE
    _JOB_TITLE = (title or "").strip()


def _listing_pick(page, title):
    """(state, cand). None when the page is not a listing: fewer than two same-named apply controls that each sit in a
    card. 'match' + the control whose card names `title` (>=60% of its words); 'no_match' when it is a listing but no
    card names this job, so we must not click a random one. Pure reading: clicks nothing."""
    toks = set(re.findall(r"[a-z0-9]+", title.lower()))
    if not toks:
        return None, None
    # the page IS this job's posting (its heading / title names it): several Apply buttons are the same job's top and
    # bottom buttons, not a listing (Accenture: two 'Apply for this job')
    try:
        head = page.evaluate("() => ((document.querySelector('h1') || {}).innerText || '') + ' ' + document.title") or ""
    except Exception:
        head = ""
    htoks = set(re.findall(r"[a-z0-9]+", head.lower()))
    if len(toks & htoks) >= max(1, round(0.6 * len(toks))):
        return None, None
    cands = []
    for idx, fr in enumerate(page.frames):
        if idx and _frame_is_ad(fr):
            continue
        try:
            rows = fr.evaluate(_CLICKABLES_JS) or []
        except Exception:
            continue
        for c in rows:
            name = (c.get("name") or "").strip().lower()
            if c.get("card") and _best_apply([{"name": name}]) is not None:
                c["frame"] = idx
                cands.append(c)
    if not any(n >= 2 for n in Counter((c.get("name") or "").strip().lower() for c in cands).values()):
        return None, None
    best, best_score = None, 0.0
    for c in cands:
        words = set(re.findall(r"[a-z0-9]+", c["card"].lower()))
        score = len(toks & words) / len(toks)
        if score >= 0.6 and score > best_score:
            best, best_score = c, score
    return ("match", best) if best else ("no_match", None)


def _frame_is_ad(fr) -> bool:
    title = name = ""
    try:
        el = fr.frame_element()
        title, name = el.get_attribute("title") or "", el.get_attribute("name") or ""
    except Exception:
        pass
    return _is_ad_frame(fr.url, title, name)


def _hop(page, aff):
    """Click an Apply affordance (in its own frame) through `act`: follow a new tab if one opens, wait until the page
    is quiet, log what the click produced into the trail. Returns the active page."""
    ctx = page.context
    fidx = aff.get("frame", 0)
    clicker = page.frames[fidx] if fidx < len(page.frames) else page
    ref, name, role = aff.get("ref"), aff["name"], aff["role"]
    loc = (clicker.locator(ref).first if ref
           else clicker.get_by_role(role, name=name, exact=True).first)
    from .clicks import act

    def click():
        try:
            loc.click(timeout=5000, no_wait_after=True)
        except Exception:
            # Covered by a consent/chatbot overlay, or a JS-handler <a> with no href:
            # dispatch the click straight to the element (bypasses the overlay).
            try:
                loc.dispatch_event("click")
            except Exception:
                clicker.get_by_role(role, name=name, exact=False).first.click(timeout=5000, no_wait_after=True)
    try:
        obs = act(page, click, max_wait_ms=12000)   # click once, follow a new tab, wait until the page is quiet
    except Exception:
        return page                     # no click landed
    for note in obs.intercepts:
        trail_note(step="intercept", note=note)
    active = obs.page
    for _ in range(3):                  # quiet but the form not mounted yet (SPA route resolving): short grace
        try:
            if _real_field_count(active) >= 2:
                break
            active.wait_for_timeout(1000)
        except Exception:
            active = ctx.pages[-1] if ctx.pages else page
            break
    return active


def _known_clicks(url: str) -> list:
    """Click names the ATS graph learned for this URL's site (empty when unknown). Never raises."""
    try:
        from .ats_lookup import site_hint
        hint = site_hint(url)
    except Exception:
        return []
    if not hint:
        return []
    clicks = list(hint["reach_clicks"])
    trail_note(step="graph_hint", site=hint["id"], clicks=clicks)
    print(f"[ats] known route for {hint['id']}: {' -> '.join(clicks)}", flush=True)
    return clicks


def reach_application_form(page, max_hops=4):
    active, status = _reach(page, max_hops)
    trail_note(step="reach_end", status=status, url=_bare(active.url))
    return active, status


def _reach(page, max_hops=4):
    """Drill from any landing (JD / search / SPA) to the real application form by
    following the Apply affordance until real applicant fields appear. Bounded and
    loop-safe (a no-progress hop stops it). Login/OTP/captcha gates are returned
    for the caller to escalate — never auto-passed; a kept apply modal with no
    fields and no way forward returns "site_refused" (the site refuses the
    application — see _kept_modal_refusal). Returns (active_page, status)."""
    active = page
    clicked = set()                        # affordance refs already clicked
    last_url = active.url
    prefer = _known_clicks(active.url)      # ATS-graph: the route this site's Apply took last time
    for _ in range(max_hops):
        if active.url != last_url:          # new page -> refs are fresh
            clicked.clear()
            last_url = active.url
            prefer = prefer or _known_clicks(active.url)
        prepare(active)
        st = classify_entry(active)
        if st == "closed":
            return active, "closed"
        if st in ("email_auth", "password"):
            return active, st              # account/login wall FIRST — an account
            # page has applicant fields AND a password; the wall wins -> escalate
        # A listing (several job cards, each with its own Apply): open THIS job's card before accepting any form on the
        # page — the form already shown may be a site contact form. Once that card is open, its form is the application.
        listing, pick = _listing_pick(active, _JOB_TITLE) if _JOB_TITLE else (None, None)
        if listing == "no_match":
            trail_note(step="listing", result="no_match", url=_bare(active.url))
            return active, "none"
        if listing == "match" and pick.get("ref") not in clicked:
            clicked.add(pick.get("ref"))
            before = active.url
            active = _hop(active, pick)
            trail_note(step="hop", click=pick["name"], role=pick["role"], frame=pick.get("frame", 0),
                       url_before=_bare(before), url_after=_bare(active.url), listing=True)
            continue
        if is_application_form(active):    # a real personal-info form -> arrived
            return active, "form"
        # Follow an Apply affordance FIRST: a JD/search page has one, a real form
        # step does not — so this avoids mistaking a JD (with a similar-jobs
        # "Next" carousel) for a wizard step. Poll briefly for a late-rendering
        # Apply control (Phenom's JD is JS-heavy). Skip affordances already
        # clicked so a dropdown TOGGLE is followed by its revealed menu OPTION.
        aff = find_apply_affordance(active, exclude=clicked, prefer=prefer)
        if aff is None:
            for _ in range(6):
                try:
                    active.wait_for_timeout(1000)
                except Exception:
                    # page navigated/closed mid-poll; switch to newest page
                    ctx = active.context
                    active = ctx.pages[-1] if ctx.pages else active
                    break
                if is_application_form(active):
                    return active, "form"
                late = classify_entry(active)      # a slow sign-in page (passport.amazon.jobs) draws after we looked
                if late in ("email_auth", "password"):
                    return active, late
                aff = find_apply_affordance(active, exclude=clicked, prefer=prefer)
                if aff is not None:
                    break
        if aff is not None:
            clicked.add(aff.get("ref"))
            before = active.url
            active = _hop(active, aff)
            trail_note(step="hop", click=aff["name"], role=aff["role"], frame=aff.get("frame", 0),
                       url_before=_bare(before), url_after=_bare(active.url))
            continue
        if _manual_option_hop(active):      # no Apply left, but a choose-how-to-apply page: its manual option opens the form
            trail_note(step="hop", click="manual application option", url_before=_bare(active.url))
            continue
        # No Apply left to follow: are we already ON a form step (wizard whose
        # first screen is a screening question, so is_application_form missed it)?
        if _is_wizard_step(active):
            return active, "form"
        nxt = _try_url_variants(active)
        if nxt is not None:
            trail_note(step="url_variant", url_after=_bare(nxt.url))
            active = nxt
            continue
        break
    reached = is_application_form(active) or _is_wizard_step(active)
    if reached:
        return active, "form"
    refusal = _kept_modal_refusal(active)     # a formless, dead-end apply modal = the site refusing
    if refusal:
        trail_note(step="site_refused", modal=refusal["head"][:60], quote=refusal["quote"][:160])
        return active, "site_refused"
    return active, classify_entry(active)


def _try_url_variants(page):
    """ATS-route fallback when no Apply affordance is found: Lever /apply, Ashby
    /application. Returns the page if a form appears, else None — back on the page it started from, never left on a
    guessed URL's 404."""
    start = page.url
    for variant in _apply_url_variants(page.url):
        try:
            page.goto(variant, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            if is_application_form(page):
                return page
        except Exception:
            pass
    if page.url != start:
        try:
            page.goto(start, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
        except Exception:
            pass
    return None


def _apply_url_variants(url: str) -> list:
    """ATS-specific apply routes to try if clicking Apply didn't reach a form.
    Lever forms live at {job}/apply, Ashby at {job}/application."""
    u = url.split("?")[0].split("#")[0].rstrip("/")
    if u.endswith(("/apply", "/application")):
        return []
    out = []
    if "career.infosys.com/jobdesc" in url:
        qs = url.split("?")[1] if "?" in url else ""
        out.append(f"https://career.infosys.com/jobs/jobapply?{qs}")
    if "ashbyhq.com" in url:
        out.append(u + "/application")
    if "lever.co" in url:
        out.append(u + "/apply")
    if not out:                                   # generic last try
        out.append(u + "/apply")
    return out


def new_tab_since(page, before):
    """The newest tab opened since the `before` snapshot of context.pages, else `page` itself. Never "the last tab":
    other jobs' tabs stay open in the same Chrome, and the last one is not this job's."""
    try:
        fresh = [p for p in page.context.pages if p not in before and not p.is_closed()]
    except Exception:
        return page
    return fresh[-1] if fresh else page


def enter_application(page) -> str:
    """Reach the application form from a JD/landing page. Thin wrapper over the
    bounded drill (`reach_application_form`); returns the status only. Callers
    that need the possibly-new active page should call `reach_application_form`."""
    _, st = reach_application_form(page)
    return st


_INTERACTIVE_GATES = {"recaptcha_v2_checkbox", "recaptcha_v2_image",
                      "hcaptcha_checkbox", "hcaptcha_image"}


def _fill_otp(page, code):
    code = "".join(c for c in str(code) if c.isdigit())[:6]
    boxes = [page.query_selector(f'input[name="pin-code-{i}"]') for i in range(1, 7)]
    boxes = [b for b in boxes if b]
    if not boxes:
        boxes = page.query_selector_all('input[aria-label*="verification code digit" i]')
    if not boxes:
        return False
    for b, ch in zip(boxes, code):
        try: b.click(); b.fill(ch)
        except Exception: pass
    return True


def _advance(page, names=("NEXT", "Next", "Continue", "Verify", "Submit")):
    for n in names:
        try:
            el = page.get_by_role("button", name=n, exact=False).first
            if el.count() > 0:
                from .clicks import act
                act(page, lambda: el.click(timeout=5000, no_wait_after=True)); return True
        except Exception:
            pass
    return False


def email_auth(page, email, otp_reader, on_captcha=None) -> str:
    """Passwordless email-first auth: fill email -> (captcha via on_captcha) ->
    NEXT/Apply now -> OTP or magic-link (via otp_reader) -> form.
    NEVER fills a password / ticks T&C.
    Returns classify_entry of where it lands ('form' on success, else a reason)."""
    from ..browser.gate_probe import classify_gate
    from .clicks import wait_until_stable
    try:
        page.fill('input[type=email], input[name*="mail" i]', email)
    except Exception:
        return "none"
    gate = classify_gate(page)
    if gate in _INTERACTIVE_GATES:
        if on_captcha is None or not on_captcha(page, gate):
            return "captcha"
    _advance(page, ("NEXT", "Next", "Continue", "Verify", "Submit",
                    "Apply now", "Apply", "Start", "Get started"))     # settles via act
    if page.query_selector('input[name="pin-code-1"], input[aria-label*="verification code digit" i]'):
        code = otp_reader() if otp_reader else None
        if not code:
            return "otp_timeout"
        if str(code).startswith("http"):    # magic link — navigate instead of OTP
            page.goto(code, wait_until="domcontentloaded")
            wait_until_stable(page)
        else:
            _fill_otp(page, code)
            _advance(page)
    else:
        # No OTP boxes visible — ZF/Phenom-style: may show "check your email" or
        # navigate directly to the form via a magic link the user clicks.
        cur = classify_entry(page)
        if cur not in ("form", "email_auth"):
            code = otp_reader() if otp_reader else None
            if code and str(code).startswith("http"):
                page.goto(code, wait_until="domcontentloaded")
                wait_until_stable(page)
    return classify_entry(page)


def untick_opt_ins(page, extra_patterns=(), tag="fill") -> int:
    """Untick pre-ticked OPTIONAL opt-ins before moving on (LinkedIn's "Follow <company>", Indeed's job-alert mails, an
    Oracle career site's "I agree to receive updates about new job opportunities" — live Cummins 2026-10-18): applying
    is not consent to be followed or mailed. Only checked, non-required boxes whose label reads as an opt-in
    (screen_review._MARKETING) or matches `extra_patterns`. Returns how many were unticked."""
    from ..orchestrator.screen_review import _MARKETING
    pats = [re.compile(p, re.I) for p in extra_patterns] + [_MARKETING]
    n = 0
    try:
        boxes = page.locator("input[type=checkbox]:checked:not([required]):not([aria-required=true])")
        for i in reversed(range(boxes.count())):
            b = boxes.nth(i)
            label = b.evaluate("e => ((e.labels && e.labels[0] ? e.labels[0].innerText : '') || e.getAttribute('aria-label')"
                               " || (e.closest('label') || e.parentElement || {}).innerText || '').trim()")
            if label and any(p.search(label) for p in pats):
                try:
                    b.uncheck(timeout=5000, force=True)
                except Exception:
                    b.evaluate("e => e.click()")          # a drawn box over a hidden input (as Oracle's consent box)
                n += 1
                print(f"[{tag}] unticked optional box {label[:60]!r}", flush=True)
    except Exception:
        pass
    return n


def prepare(page) -> None:
    """Idempotent per-step page prep: clear cookie overlays and idle dialogs."""
    try: dismiss_consent(page)
    except Exception: pass
    try: dismiss_dialogs(page)
    except Exception: pass
    # Taleo: dismiss stale "already attached" overwrite modal (plain HTML, not [role=dialog])
    try:
        clicked = page.evaluate("""() => {
            if (!document.body.innerText.includes('already been attached')) return false;
            for (const el of document.querySelectorAll(
                    'input[type=button], input[type=submit], button')) {
                const v = (el.value || el.textContent || '').trim();
                if (/^no$/i.test(v)) { el.click(); return true; }
            }
            return false;
        }""")
        if clicked:
            page.wait_for_timeout(800)
            print("[prep] dismissed stale Taleo overwrite modal", flush=True)
    except Exception:
        pass
