"""Operator-supplied credential handling for ATS account/login walls.
Per-ATS register/login flows: Darwinbox, Infosys, SmartRecruiters. Generic fallback: _fill_wall.
Credentials stored in ~/.career_agent/credentials.json (plaintext — operator use only).
"""
from __future__ import annotations

import json
import os
import secrets
import string
from pathlib import Path

_STORE = Path.home() / ".career_agent" / "credentials.json"

# SAP SuccessFactors allows only alphanumeric + a limited special set; avoid
# characters that trigger extra escaping or clipboard issues.
_SPECIALS = "!#$%-+=@"  # @ required by Darwinbox
_ALPHABET = string.ascii_letters + string.digits + _SPECIALS


def generate_password(length: int = 16) -> str:
    """16-char random password meeting most ATS policies (upper+lower+digit+special)."""
    # ponytail: simple guarantee loop; cost is negligible for short passwords
    while True:
        pwd = [
            secrets.choice(string.ascii_uppercase),
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.digits),
            secrets.choice(_SPECIALS),
        ] + [secrets.choice(_ALPHABET) for _ in range(length - 4)]
        secrets.SystemRandom().shuffle(pwd)
        result = "".join(pwd)
        if (any(c.isupper() for c in result) and any(c.islower() for c in result)
                and any(c.isdigit() for c in result)):
            return result


def save_credential(site: str, username: str, password: str, label: str = "",
                    **extra) -> None:
    # ponytail: plaintext JSON; upgrade to system keyring if secrets matter more
    key = f"{site}:{label}" if label else site
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    data: dict = json.loads(_STORE.read_text()) if _STORE.exists() else {}
    data[key] = {"username": username, "password": password, "label": label, **extra}
    _STORE.write_text(json.dumps(data, indent=2))


def load_credential(site: str, label: str = "") -> dict | None:
    """Return ``{"username": ..., "password": ..., "label": ...}`` or ``None``."""
    if not _STORE.exists():
        return None
    key = f"{site}:{label}" if label else site
    return json.loads(_STORE.read_text()).get(key)


def _default_email() -> str:
    return os.getenv("CAREER_AGENT_EMAIL", "")


def _email_on_page(page) -> str:
    """Read whatever is already typed into the email field, or fall back to profile."""
    try:
        el = page.query_selector(
            'input[type="email"], input[name*="email" i], input[id*="email" i]'
        )
        return (el.input_value() if el else "") or _default_email()
    except Exception:
        return _default_email()


def _type_into(page, el, value: str) -> None:
    """Click an input and type value using native keyboard events (isTrusted=True)."""
    el.click()
    page.keyboard.press("Control+a")
    page.keyboard.type(value, delay=30)   # slight delay = more human-like
    page.keyboard.press("Tab")            # blur so the field commits
    page.wait_for_timeout(300)


def _fill_wall(page, gate: str, cred: dict) -> None:
    """Fill the login/signup wall fields and submit.

    Uses native keyboard events only (isTrusted=True) so framework validators accept
    them. Handles both simple login forms and registration forms with confirmation
    fields (e.g. SAP SuccessFactors).
    """
    try:
        # Email — try strict type first, then name/id heuristics (SF uses type=text)
        email_sel = (
            'input[type="email"],'
            'input[name*="email" i], input[id*="email" i],'
            'input[name*="userName" i], input[id*="userName" i],'
            'input[name*="user_name" i]'
        )
        email_filled = False
        for el in page.query_selector_all(email_sel):
            if el.is_visible():
                _type_into(page, el, cred["username"])
                email_filled = True
        if not email_filled:
            # Fallback: accessible-name label search (covers Workday id="input-N" style)
            try:
                el = page.get_by_label("email", exact=False).first
                if el.count() > 0 and el.is_visible():
                    _type_into(page, el, cred["username"])
            except Exception:
                pass

        if gate == "password":
            for el in page.query_selector_all('input[type="password"]'):
                if el.is_visible():
                    _type_into(page, el, cred["password"])

        # First / last name (registration forms)
        for name_sel, val in [
            ('input[name*="fName" i], input[id*="first" i], input[name*="firstName" i]',
             cred.get("first_name", "")),
            ('input[name*="lName" i], input[id*="last" i], input[name*="lastName" i]',
             cred.get("last_name", "")),
        ]:
            if not val:
                continue
            el = page.query_selector(name_sel)
            if el and el.is_visible():
                _type_into(page, el, val)

        page.wait_for_timeout(800)   # let async validators settle before submit
        # Try type="submit" first; many ATSs (Workday, etc.) use type="button" instead
        submit = page.query_selector('button[type="submit"], input[type="submit"]')
        if not submit or not submit.is_visible():
            for btn_name in ("Create Account", "Sign In", "Log In", "Sign Up",
                             "Register", "Submit", "Continue"):
                try:
                    btn = page.get_by_role("button", name=btn_name, exact=False).first
                    if btn.count() > 0 and btn.is_visible():
                        submit = btn
                        break
                except Exception:
                    pass
        if submit:
            submit.click()
            page.wait_for_timeout(2500)
    except Exception:
        pass


def _dbx_type(page, formcontrolname: str, value: str) -> bool:
    host = page.query_selector(f'dbx-textinput[formcontrolname="{formcontrolname}"]')
    if not host:
        return False
    inp_handle = host.evaluate_handle(
        "(el) => el.shadowRoot && el.shadowRoot.querySelector('input')"
    )
    inp = inp_handle.as_element()
    if not inp:
        return False
    try:
        inp.click()
        page.keyboard.press("Control+a")
        page.keyboard.type(value, delay=40)
        page.wait_for_timeout(200)
        return True
    except Exception:
        return False


def _darwinbox_spa_url(source: str, path: str) -> str:
    """Derive a Darwinbox SPA URL (e.g. /auth/register) from any URL on the same app."""
    import re as _re
    from urllib.parse import urlparse
    m = _re.match(r"(https?://[^/]+(?:/[^/]+)*/ms/candidatev2/main)", source)
    if m:
        return m.group(1) + path
    parsed = urlparse(source)
    return f"{parsed.scheme}://{parsed.netloc}/ms/candidatev2/main{path}"


def _darwinbox_google_signin(page, original_url: str | None = None) -> bool:
    import os as _os
    _google_email = _os.getenv("CAREER_AGENT_EMAIL") or _default_email()

    try:
        for label in ("Sign Up with Google", "Sign In with Google"):
            btn = page.get_by_text(label, exact=True)
            if btn.count() == 0:
                continue
            btn.first.click()
            print(f"[darwinbox] clicked '{label}'", flush=True)
            page.wait_for_timeout(4000)
            url = page.url
            print(f"[darwinbox] after google click URL: {url}", flush=True)

            if "accounts.google.com" in url:
                # Try clicking the right account if chooser is shown
                for sel in [
                    f'[data-email="{_google_email}"]',
                    f'[aria-label*="{_google_email}"]',
                    f'li[role="presentation"]',   # first account in list
                ]:
                    try:
                        el = page.query_selector(sel)
                        if el and el.is_visible():
                            el.click()
                            print(f"[darwinbox] selected Google account via {sel}", flush=True)
                            page.wait_for_timeout(5000)
                            break
                    except Exception:
                        pass

                url = page.url
                print(f"[darwinbox] after account select URL: {url}", flush=True)

            if ("darwinbox.in" in url or "darwinbox.com" in url) and "/auth/" not in url:
                print("[darwinbox] Google sign-in succeeded", flush=True)
                if original_url:
                    page.goto(original_url)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=12000)
                    except Exception:
                        pass
                    page.wait_for_timeout(2000)
                return True

            return False
    except Exception as e:
        print(f"[darwinbox] google signin error: {e}", flush=True)
    return False


def _darwinbox_register(page, cred: dict, original_url: str | None = None) -> None:
    import time as _t, pathlib as _pl
    _otp_file = _pl.Path("/tmp/career_agent_otp.txt")

    try:
        source = original_url or page.url
        reg_url = _darwinbox_spa_url(source, "/auth/register")
        print(f"[darwinbox] navigating to registration: {reg_url}", flush=True)
        page.goto(reg_url)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=12000)
        except Exception:
            pass
        page.wait_for_timeout(2000)

        # Step 1: fill email, then wait for Verify button to render
        _dbx_type(page, "email", cred["username"])
        page.wait_for_timeout(2000)

        verify_clicked = False
        for locator in [page.get_by_text("Verify", exact=True),
                        page.get_by_role("button", name="Verify")]:
            try:
                if locator.count() > 0 and locator.first.is_visible():
                    locator.first.click(); verify_clicked = True
                    print(f"[darwinbox] clicked Verify — OTP to {cred['username']}", flush=True)
                    break
            except Exception:
                pass
        if not verify_clicked:
            print("[darwinbox] Verify button not found", flush=True)

        page.wait_for_timeout(3000)  # Cloudflare Turnstile auto-solve

        if verify_clicked:
            _otp_file.unlink(missing_ok=True)
            token = None
            print("[darwinbox] waiting for OTP (/tmp/career_agent_otp.txt)…", flush=True)
            for _ in range(150):
                _t.sleep(2)
                if _otp_file.exists():
                    v = _otp_file.read_text().strip()
                    if v:
                        _otp_file.unlink(missing_ok=True); token = v; break
            if token:
                if not _dbx_type(page, "otp", token):
                    for el in page.query_selector_all('input[type="text"], input[type="number"], input[inputmode="numeric"]'):
                        if el.is_visible():
                            try: el.click(); page.keyboard.press("Control+a"); page.keyboard.type(token, delay=40)
                            except Exception: pass
                            break
                page.wait_for_timeout(1000)
            else:
                print("[darwinbox] OTP timeout — proceeding anyway", flush=True)

        # Step 5: password + confirm
        _dbx_type(page, "password", cred["password"])
        page.wait_for_timeout(2000)
        _dbx_type(page, "confirm", cred["password"])
        page.wait_for_timeout(2000)

        # Step 6: T&C checkbox
        terms = page.query_selector('input#terms')
        if terms and not terms.is_checked():
            terms.check()
        page.wait_for_timeout(2000)

        # Sign Up — retry up to 2× for transient captcha
        for attempt in range(3):
            submit = page.query_selector('button[type="submit"]')
            if submit:
                submit.click()
                print(f"[darwinbox] sign-up submit attempt {attempt + 1}", flush=True)
                page.wait_for_timeout(4000)
            if "/auth/register" not in page.url:
                break
            if attempt < 2:
                print("[darwinbox] still on register page, retrying in 2 s", flush=True)
                page.wait_for_timeout(2000)
            else:
                print("[stop] captcha on Darwinbox register — solve manually then re-run", flush=True)

        print(f"[darwinbox] after register URL: {page.url}", flush=True)
        try:
            page.screenshot(path="/tmp/darwinbox_post_register.png", full_page=False)
            print("[darwinbox] screenshot: /tmp/darwinbox_post_register.png", flush=True)
        except Exception:
            pass
    except Exception as e:
        print(f"[darwinbox] registration error: {e}", flush=True)


def _darwinbox_login(page, cred: dict, original_url: str | None = None) -> None:
    """Navigate to Darwinbox /auth/login and sign in via JS shadow-DOM fill."""
    try:
        source = original_url or page.url
        login_url = _darwinbox_spa_url(source, "/auth/login")
        print(f"[darwinbox] navigating to login: {login_url}", flush=True)
        page.goto(login_url)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=12000)
        except Exception:
            pass
        page.wait_for_timeout(4000)  # Angular boot + Cloudflare Turnstile auto-solve

        _dbx_type(page, "email", cred["username"])
        _dbx_type(page, "password", cred["password"])
        page.wait_for_timeout(1000)  # let Turnstile finish if still pending

        submit = page.query_selector('button[type="submit"]')
        if submit:
            submit.click()
            print("[darwinbox] submitted login form", flush=True)
            page.wait_for_timeout(6000)  # wait for redirect on success
        print(f"[darwinbox] after login URL: {page.url}", flush=True)

        if original_url:
            print(f"[darwinbox] navigating back to job: {original_url}", flush=True)
            page.goto(original_url)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=12000)
            except Exception:
                pass
            page.wait_for_timeout(2000)
    except Exception as e:
        print(f"[darwinbox] login error: {e}", flush=True)


# ponytail: JS fill because keyboard.type doesn't commit to Angular formControl.
# Accepts a CSS selector string OR an integer index into querySelectorAll('input').
_INFOSYS_JS = """([q, v]) => {
    const el = typeof q === 'number'
        ? document.querySelectorAll('input')[q]
        : document.querySelector(q);
    if (!el) return;
    el.focus(); el.value = v;
    ['input','change'].forEach(t => el.dispatchEvent(new Event(t, {bubbles:true})));
    el.blur(); el.dispatchEvent(new Event('blur', {bubbles:true}));
}"""


def _infosys_register(page, cred: dict, original_url: str | None = None) -> None:
    # Register form fields by querySelectorAll index:
    # 0=firstnameX, 1=middle(skip), 2=lastName, 3=email(type=text!), 4=pw, 5=confirmPw, 6=checkbox
    try:
        print("[infosys] navigating to registration", flush=True)
        page.goto("https://career.infosys.com/register")
        try: page.wait_for_load_state("networkidle", timeout=15000)
        except Exception: pass
        page.wait_for_timeout(3000)
        page.evaluate(_INFOSYS_JS, ['input[name="firstnameX"]', cred.get("first_name", "")])
        page.evaluate(_INFOSYS_JS, [2, cred.get("last_name", "")])
        page.evaluate(_INFOSYS_JS, [3, cred["username"]])
        page.evaluate(_INFOSYS_JS, [4, cred["password"]])
        page.evaluate(_INFOSYS_JS, [5, cred["password"]])
        page.evaluate("""() => {
            const cb = document.querySelector('input[type="checkbox"]');
            if (cb && !cb.checked) { cb.checked = true;
                cb.dispatchEvent(new Event('change', {bubbles:true})); }
        }""")
        page.wait_for_timeout(500)
        submit = page.query_selector('button[type="submit"], input[type="submit"]')
        if submit:
            submit.click()
            print("[infosys] submitted registration form", flush=True)
            page.wait_for_timeout(5000)
        print(f"[infosys] after register URL: {page.url}", flush=True)
    except Exception as e:
        print(f"[infosys] registration error: {e}", flush=True)


def _infosys_login(page, cred: dict, original_url: str | None = None) -> None:
    # Keycloak login page (intapidm) — use native fill so the form submits correctly
    try:
        print(f"[infosys] login page: {page.url}", flush=True)
        # Keycloak standard HTML form: fill natively so browser sees real keystrokes
        usr = page.query_selector('input[name="username"], input[id="username"]')
        pwd = page.query_selector('input[type="password"]')
        if usr: usr.fill(cred["username"])
        if pwd: pwd.fill(cred["password"])
        try: page.wait_for_selector('button[type="submit"]', timeout=8000)
        except Exception: pass
        submit = page.query_selector('button[type="submit"], input[type="submit"], button#btnSubmit, form button')
        if submit:
            submit.click()
            print("[infosys] submitted login form", flush=True)
        try: page.wait_for_load_state("networkidle", timeout=15000)
        except Exception: pass
        page.wait_for_timeout(3000)
        print(f"[infosys] after login URL: {page.url}", flush=True)
        # Dismiss any post-login popup (e.g. "Important Notice")
        try:
            ok = page.query_selector('button:has-text("Ok"), button:has-text("OK")')
            if ok: ok.click(); page.wait_for_timeout(1000)
        except Exception: pass
        # Navigate back to the job page so enter_application runs on the JD
        if original_url and "infosys" in original_url:
            page.goto(original_url, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
        # Accept Privacy and Data Protection consent shown on first login
        try:
            if "Privacy and Data Protection" in (page.inner_text("body") or ""):
                page.evaluate("()=>{document.querySelectorAll('div').forEach(d=>{if(d.scrollHeight>d.clientHeight+50)d.scrollTop=d.scrollHeight;});window.scrollTo(0,document.body.scrollHeight);}")
                page.evaluate("()=>{document.querySelectorAll('input[type=\"checkbox\"]').forEach(cb=>{if(!cb.checked){cb.checked=true;cb.dispatchEvent(new Event('change',{bubbles:true}));}});}")
                btn = page.query_selector("button:has-text('Accept')")
                if btn: btn.click(); page.wait_for_timeout(3000)
                print(f"[infosys] after privacy: {page.url}", flush=True)
        except Exception: pass
    except Exception as e:
        print(f"[infosys] login error: {e}", flush=True)


_LOGIN_TEXTS = [
    "sign in", "log in", "login", "already have an account",
    "existing user", "have an account", "back to login", "returning user",
]
_SIGNUP_TEXTS = [
    "sign up", "register", "create account", "create an account",
    "new user", "don't have an account", "no account", "new here",
    "join now", "get started", "new to",
]


def _navigate_to_form(page, link_texts: list[str], label: str) -> bool:
    try:
        for el in page.query_selector_all("a, button"):
            if not el.is_visible():
                continue
            text = (el.text_content() or "").strip().lower()
            if any(t in text for t in link_texts):
                print(f"[cred] navigating to {label}: {text!r}", flush=True)
                el.click()
                page.wait_for_timeout(2000)
                return True
    except Exception:
        pass
    return False


def _ensure_login_form(page) -> None:
    """If on a sign-up page but have credentials, click through to login."""
    _navigate_to_form(page, _LOGIN_TEXTS, "login form")


def _ensure_signup_form(page) -> None:
    _navigate_to_form(page, _SIGNUP_TEXTS, "sign-up form")


def provide(page, gate: str, site: str, original_url: str | None = None,
            email: str = "") -> bool:
    """Fill an account/login wall using stored or freshly-generated credentials."""
    if "infosys" in site or "intapidm" in site:
        site = "career.infosys.com"   # canonical key regardless of which domain triggered
    cred = load_credential(site, label=gate)
    is_new = cred is None
    if cred is None:
        username = _email_on_page(page) or email or _default_email()
        password = generate_password()
        extra = {
            "first_name": os.getenv("CAREER_AGENT_FIRST_NAME", "Rakshit"),
            "last_name": os.getenv("CAREER_AGENT_LAST_NAME", "Singh"),
        }
        save_credential(site, username, password, label=gate, **extra)
        cred = {"username": username, "password": password, "label": gate, **extra}

    if "darwinbox" in site:
        if is_new:
            _darwinbox_register(page, cred, original_url=original_url)
        _darwinbox_login(page, cred, original_url=original_url)
    elif "infosys" in site:
        if is_new:
            _infosys_register(page, cred, original_url=None)
        _infosys_login(page, cred, original_url=original_url)
    elif "smartrecruiters" in site:
        # SR non-OneClick: account modal appears on the JD page after clicking Apply.
        # Generic _fill_wall covers login (email+password) and registration
        # (click "Create an account" → fill name+email+password+confirm).
        # ponytail: if SR requires email OTP for new accounts, wire _sr_register() here.
        print(f"[sr] {'registering' if is_new else 'logging in'} on {site}", flush=True)
        if is_new:
            _ensure_signup_form(page)
        else:
            _ensure_login_form(page)
        _fill_wall(page, gate, cred)
    else:
        if is_new:
            _ensure_signup_form(page)
        else:
            _ensure_login_form(page)
        _fill_wall(page, gate, cred)
    return True
