"""Reusable page-prep tools: clear overlays/noise and get the walk to the real
application form. DOM tools are idempotent and never click a submit/destructive
control; suppress_noise is pure. LLM-free."""
from __future__ import annotations

import re

# Fields that are never real application inputs.
_NOISE_RE = re.compile(
    r"oda-|ask me something|add summary|work-summary|honey.?pot|"
    r"g-recaptcha-response|h-captcha-response", re.I)


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


_DECLINE = ["Decline", "Reject all", "Reject", "Only necessary", "Necessary only", "Refuse"]
_ACCEPT = ["Accept all", "Accept", "Agree", "OK", "Got it", "I understand"]
_DIALOG_DISMISS = ["Continue Working", "Continue", "Stay", "Stay signed in", "Dismiss", "Close"]


def _click_first(page, names, within=None):
    root = within or page
    for name in names:
        try:
            btn = root.get_by_role("button", name=name, exact=False).first
            if btn.count() == 0:
                btn = root.get_by_role("link", name=name, exact=False).first
            if btn.count() > 0:
                btn.click(timeout=3000)
                page.wait_for_timeout(400)
                return name
        except Exception:
            pass
    return None


def _looks_consent(page) -> bool:
    try:
        return bool(page.evaluate(
            "() => /cookie|consent|privacy preferences|we use/i"
            ".test(document.body.innerText.slice(0,3000))"))
    except Exception:
        return False


def dismiss_consent(page) -> bool:
    """Decline a cookie/consent overlay if offered, else OK/Accept to unblock.
    Site cookie banners ONLY — never an application T&C/attestation."""
    if not _looks_consent(page):
        return False
    if _click_first(page, _DECLINE):
        return True
    return _click_first(page, _ACCEPT) is not None


def dismiss_dialogs(page) -> bool:
    """Dismiss an idle/blocking modal (e.g. Oracle 'Continue Working'). Never a
    destructive/submit control."""
    try:
        if page.locator("[role=dialog], [role=alertdialog]").first.count() == 0:
            return False
    except Exception:
        return False
    return _click_first(page, _DIALOG_DISMISS) is not None


_CLOSED_RE = re.compile(
    r"job (not found|you requested was not found)|no longer available"
    r"|could ?n'?t find anything|posting[^.]{0,40}(closed|removed)|404 error",
    re.I)


def _looks_closed(text: str) -> bool:
    """True if the page is a dead-posting shell (expired/removed/404). Guarded to
    a short body so a long JD that merely mentions '404' isn't flagged."""
    t = (text or "").strip()
    if not t or len(t) > 600:
        return False
    return _CLOSED_RE.search(t) is not None


def is_closed_posting(page) -> bool:
    try:
        return _looks_closed(page.evaluate("() => document.body.innerText"))
    except Exception:
        return False


def classify_entry(page, status=None) -> str:
    """Which of the two application shapes (or a JD/password gate) is on screen:
    'closed' | 'form' | 'email_auth' | 'password' | 'none'.

    Reasoning for 'closed': a 404/410 HTTP status is decisive; otherwise it needs
    BOTH no fillable form AND dead-posting language — so a live form is never
    'closed', and a page that's alive but whose form we didn't reach is 'none'
    (a different problem: a second hop / login / render), not 'closed'."""
    if status in (404, 410):
        return "closed"
    try:
        d = page.evaluate("""() => {
          const vis = e => { const r=e.getBoundingClientRect(); return r.width>4 && r.height>4; };
          const ins = Array.from(document.querySelectorAll('input,select,textarea')).filter(vis);
          const txt = document.body.innerText.slice(0, 4000);
          const hasPw = ins.some(e => e.type === 'password')
                        || /create a password|sign in with password/i.test(txt);
          const email = ins.find(e => e.type === 'email' || /mail/i.test(e.name||e.id||''));
          const fillable = ins.filter(e => !['hidden','submit','button','password'].includes(e.type)
            && !/search/i.test(e.getAttribute('aria-label')||e.name||'')).length;
          return { hasPw, hasEmail: !!email,
            verify: /verify|one-time|we'll send|continue with email|create .*profile|confirm your identity/i.test(txt),
            fillable };
        }""")
    except Exception:
        return "none"
    if d["hasPw"]:
        return "password"
    if d["hasEmail"] and d["verify"]:
        return "email_auth"
    if d["fillable"] >= 2:
        return "form"                       # a form is present -> never 'closed'
    if is_closed_posting(page):             # no form + dead-posting language -> closed
        return "closed"
    return "none"                           # no form, but alive -> unreached, not dead


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
  const vis = e => { const r=e.getBoundingClientRect(); return r.width>4 && r.height>4; };
  const ins = Array.from(document.querySelectorAll('input,select,textarea')).filter(vis);
  const seen = new Set();
  for (const e of ins) {
    if (['hidden','submit','button'].includes(e.type)) continue;
    const hay = ((e.getAttribute('aria-label')||'')+' '+(e.name||'')+' '+(e.id||'')
                 +' '+(e.placeholder||'')+' '+(e.type||'')).toLowerCase();
    let k = null;
    if (e.type==='email' || /\be-?mail\b/.test(hay)) k='email';
    else if (e.type==='file' || /resume|\bcv\b|upload/.test(hay)) k='resume';
    else if (/first name|last name|full name|your name|given name|family name|surname/.test(hay)) k='name';
    else if (/phone|mobile/.test(hay)) k='phone';
    if (k) seen.add(k);
  }
  return seen.size;
}"""

# Every visible clickable's accessible-ish name + role, for the Apply ranker.
_CLICKABLES_JS = r"""() => {
  const vis = e => { const r=e.getBoundingClientRect(); return r.width>4 && r.height>4; };
  const out = [];
  for (const e of document.querySelectorAll('button, a[href], [role=button], input[type=submit]')) {
    if (!vis(e)) continue;
    const name = (e.getAttribute('aria-label') || e.value || e.textContent || '').trim().replace(/\s+/g,' ');
    if (name) out.push({ name, role: e.tagName === 'A' ? 'link' : 'button' });
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


def _site_of(page) -> str:
    """The host the wall is on (e.g. 'career4.successfactors.com') — the per-ATS
    key an operator provider uses to generate/look up the right credential."""
    from urllib.parse import urlparse
    try:
        return (urlparse(page.url).hostname or "").lower()
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
    "apply for this job", "apply for this role", "apply to this job",
    "apply now", "apply online", "submit application", "start application",
    "apply", "get started",
)
# "interested" ("I'm interested") is the common trigger for a CONVERSATIONAL
# (chatbot) apply — a different interaction mode, not the form. Denying it keeps
# the drill on the real "Apply" when both are present; a chatbot-only page is
# handled by the dialog tool, not by pretending it's a form.
_APPLY_DENY = (
    "save", "search", "sign in", "sign up", "log in", "login", "register",
    "create account", "filter", "refer", "subscribe", "share", "print",
    "easy apply", "interested", "job alert", "view all", "back to", "learn more",
)


def _best_apply(cands):
    """cands: [{'name', 'role'}]. Return the best Apply control (highest-priority
    allow phrase, not denied), or None. Pure — the ranking core, unit-tested."""
    best, best_rank = None, len(_APPLY_ALLOW)
    for c in cands:
        name = (c.get("name") or "").strip().lower()
        if not name or len(name) > 40 or any(d in name for d in _APPLY_DENY):
            continue
        for rank, allow in enumerate(_APPLY_ALLOW):
            if allow in name:
                if rank < best_rank:
                    best, best_rank = c, rank
                break
    return best


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


def find_apply_affordance(page):
    """The best Apply button/link across all frames, as {'name','role','frame'},
    or None. `frame` is the index into page.frames the control lives in."""
    cands = []
    for idx, fr in enumerate(page.frames):
        try:
            rows = fr.evaluate(_CLICKABLES_JS)
        except Exception:
            continue
        for c in (rows or []):
            c["frame"] = idx
            cands.append(c)
    return _best_apply(cands)


def _hop(page, aff):
    """Click an Apply affordance (in its own frame), follow a new tab if one
    opens, and settle — polling for the form to mount (SPA) for ~6s. Returns the
    active page."""
    ctx = page.context
    before = len(ctx.pages)
    fidx = aff.get("frame", 0)
    clicker = page.frames[fidx] if fidx < len(page.frames) else page
    name, role = aff["name"], aff["role"]
    try:
        clicker.get_by_role(role, name=name, exact=True).first.click(timeout=5000)
    except Exception:
        try:
            clicker.get_by_role(role, name=name, exact=False).first.click(timeout=5000)
        except Exception:
            return page
    page.wait_for_timeout(1000)
    active = ctx.pages[-1] if len(ctx.pages) > before else page
    for _ in range(6):
        try:
            active.wait_for_load_state("domcontentloaded", timeout=2000)
        except Exception:
            pass
        if _real_field_count(active) >= 2:
            break
        active.wait_for_timeout(1000)
    return active


def reach_application_form(page, max_hops=3):
    """Drill from any landing (JD / search / SPA) to the real application form by
    following the Apply affordance until real applicant fields appear. Bounded and
    loop-safe (a no-progress hop stops it). Login/OTP/captcha gates are returned
    for the caller to escalate — never auto-passed. Returns (active_page, status)."""
    active = page
    seen = set()
    for _ in range(max_hops):
        prepare(active)
        st = classify_entry(active)
        if st == "closed":
            return active, "closed"
        if is_application_form(active):
            return active, "form"
        if st in ("email_auth", "password"):
            return active, st              # gate -> caller escalates
        sig = (active.url, _real_field_count(active))
        if sig in seen:
            break                          # hop made no progress -> stop
        seen.add(sig)
        aff = find_apply_affordance(active)
        if aff is None:
            nxt = _try_url_variants(active)
            if nxt is not None:
                active = nxt
                continue
            break
        active = _hop(active, aff)
    return active, ("form" if is_application_form(active) else classify_entry(active))


def _try_url_variants(page):
    """ATS-route fallback when no Apply affordance is found: Lever /apply, Ashby
    /application. Returns the page if a form appears, else None."""
    for variant in _apply_url_variants(page.url):
        try:
            page.goto(variant, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            if is_application_form(page):
                return page
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
    if "ashbyhq.com" in url:
        out.append(u + "/application")
    if "lever.co" in url:
        out.append(u + "/apply")
    if not out:                                   # generic last try
        out.append(u + "/apply")
    return out


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
                el.click(timeout=5000); page.wait_for_timeout(1200); return True
        except Exception:
            pass
    return False


def email_auth(page, email, otp_reader, on_captcha=None) -> str:
    """Passwordless email-first auth: fill email -> (captcha via on_captcha) ->
    NEXT -> OTP (via otp_reader) -> form. NEVER fills a password / ticks T&C.
    Returns classify_entry of where it lands ('form' on success, else a reason)."""
    from ..browser.gate_probe import classify_gate
    try:
        page.fill('input[type=email], input[name*="mail" i]', email)
    except Exception:
        return "none"
    gate = classify_gate(page)
    if gate in _INTERACTIVE_GATES:
        if on_captcha is None or not on_captcha(page, gate):
            return "captcha"
    _advance(page)
    page.wait_for_timeout(1500)
    if page.query_selector('input[name="pin-code-1"], input[aria-label*="verification code digit" i]'):
        code = otp_reader() if otp_reader else None
        if not code:
            return "otp_timeout"
        _fill_otp(page, code)
        _advance(page)
        page.wait_for_timeout(1500)
    return classify_entry(page)


def prepare(page) -> None:
    """Idempotent per-step page prep: clear cookie overlays and idle dialogs."""
    try: dismiss_consent(page)
    except Exception: pass
    try: dismiss_dialogs(page)
    except Exception: pass
