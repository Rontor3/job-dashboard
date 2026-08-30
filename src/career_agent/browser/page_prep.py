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


_APPLY = ["Apply now", "Apply for this job", "Apply", "I'm interested", "Start application", "Start"]


_REACHED = {"form", "email_auth", "password"}    # a hop that actually got somewhere


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
    """From a JD page (classify_entry == 'none'), reach the application form: click
    Apply ONCE (follow a same-tab nav OR a new tab), and if that doesn't land on a
    form, try the ATS-specific /apply|/application route. One hop — never a submit."""
    here = classify_entry(page)
    if here != "none":
        return here
    ctx = page.context
    before = len(ctx.pages)
    job_url = page.url
    clicked = None
    for name in _APPLY:
        try:
            el = page.get_by_role("button", name=name, exact=False).first
            if el.count() == 0:
                el = page.get_by_role("link", name=name, exact=False).first
            if el.count() > 0:
                el.click(timeout=5000); clicked = name; break
        except Exception:
            pass
    active = page
    if clicked is not None:
        page.wait_for_timeout(2500)
        if len(ctx.pages) > before:                # a new tab opened -> adopt it
            active = ctx.pages[-1]
            try: active.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception: pass
        res = classify_entry(active)
        if res in _REACHED:
            return res
    # click didn't reach a form (wrong Apply link, or no button) -> try the ATS route
    for variant in _apply_url_variants(job_url):
        try:
            active.goto(variant, wait_until="domcontentloaded")
            active.wait_for_timeout(2500)
            res = classify_entry(active)
            if res in _REACHED:
                return res
        except Exception:
            pass
    return classify_entry(active)


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
