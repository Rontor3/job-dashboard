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


def _fill_otp_generic(page, code: str) -> bool:
    """Fill a numeric OTP into individual digit boxes or a single input."""
    digits = "".join(c for c in str(code) if c.isdigit())
    # Try multi-box (Phenom/eightfold: 6 boxes with class "numberInput", no maxlength)
    for sel in (
        'input[class*="numberInput" i]',      # Phenom/eightfold OTP boxes
        'input[name^="pin-code"]',
        'input[aria-label*="digit" i]',
        'input[inputmode="numeric"][maxlength="1"]',
        'input[type="tel"][maxlength="1"]',
        'input[maxlength="1"]',
    ):
        boxes = [el for el in page.query_selector_all(sel) if el.is_visible()]
        if boxes:
            for b, ch in zip(boxes, digits):
                try:
                    b.click()
                    page.keyboard.type(ch, delay=50)
                except Exception:
                    pass
            return True
    single = page.query_selector(
        'input[name*="otp" i], input[id*="otp" i], '
        'input[name*="code" i], input[id*="code" i], '
        'input[inputmode="numeric"]'
    )
    if single and single.is_visible():
        _type_into(page, single, digits)
        return True
    return False
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


import hashlib as _hashlib
import re as _re
import time as _time


def _classify_page_state(page) -> str:
    """Read DOM + URL → return next-action hint."""
    try:
        txt = (page.inner_text("body") or "").lower()
        url = page.url.lower()
    except Exception:
        return "unknown"
    if any(d in url for d in ("accounts.google.com", "accounts.facebook.com", "linkedin.com/oauth")):
        return "oauth"
    # OTP input present
    otp_el = page.query_selector(
        'input[name*="otp" i], input[id*="otp" i],'
        'input[name*="code" i][maxlength], input[inputmode="numeric"][maxlength="1"]'
    )
    if otp_el and otp_el.is_visible():
        return "otp"
    if _re.search(r"enter.*code|verification code|check your email|one.?time password|otp", txt):
        return "otp"
    if _re.search(r"verify your email|confirm your email|verification link|click the link|we sent", txt):
        return "verify_email"
    # Registration fields (first + last name inputs visible) — check BEFORE password
    # so that account-creation forms (name + password) are classified as registration
    fname_el = page.query_selector('input[name*="first" i], input[id*="first" i],'
                                   'input[name*="fName" i], input[placeholder*="first" i]')
    if fname_el and fname_el.is_visible():
        return "registration"
    # Password field now visible (email-first: Continue was clicked, step 2 appeared)
    pw_els = page.query_selector_all('input[type="password"]')
    if any(el.is_visible() for el in pw_els):
        return "password"
    return "unknown"


def _observe_until_change(page, label: str, max_wait_s: int = 30, interval_s: int = 5) -> str:
    """Poll every interval_s sec; snapshot each tick; stop and classify when DOM changes.

    Returns the _classify_page_state result at the moment the change is detected,
    or 'unknown' if nothing changed within max_wait_s.
    """
    def _sig():
        try:
            return _hashlib.md5((page.inner_text("body") or "").encode()).hexdigest()
        except Exception:
            return ""

    initial_sig = _sig()
    elapsed = 0
    while elapsed < max_wait_s:
        _time.sleep(interval_s)
        elapsed += interval_s
        try:
            path = f"/tmp/career_agent_cred_{label}_{elapsed}s.png"
            page.screenshot(path=path, full_page=False)
            print(f"[cred] snapshot @{elapsed}s ({label}): {path}", flush=True)
        except Exception:
            pass
        current_sig = _sig()
        if current_sig != initial_sig:
            state = _classify_page_state(page)
            print(f"[cred] page changed at {elapsed}s → {state}", flush=True)
            return state
    print(f"[cred] no change after {max_wait_s}s ({label})", flush=True)
    return _classify_page_state(page)  # classify anyway even if no DOM change detected


def _is_email_first(page) -> bool:
    """True if page has visible email field but NO visible password field (email-first form)."""
    try:
        email_sel = ('input[type="email"], input[name*="email" i], input[id*="email" i],'
                     'input[name*="userName" i]')
        has_email = any(el.is_visible() for el in page.query_selector_all(email_sel))
        if not has_email:
            return False
        has_pw = any(el.is_visible() for el in page.query_selector_all('input[type="password"]'))
        return not has_pw
    except Exception:
        return False


def _click_non_social_submit(page, btn_names=("Continue", "Create Account", "Sign Up",
                                               "Register", "Sign In", "Log In", "Submit")) -> bool:
    """Click the first visible non-social submit button and return True if found."""
    submit = page.query_selector('button[type="submit"], input[type="submit"]')
    if submit and submit.is_visible():
        txt = (submit.text_content() or "").lower()
        if not any(s in txt for s in _SOCIAL_KEYWORDS):
            submit.click()
            return True
    for btn_name in btn_names:
        try:
            btn = page.get_by_role("button", name=btn_name, exact=False).first
            if btn.count() > 0 and btn.is_visible():
                txt = (btn.text_content() or "").lower()
                if not any(s in txt for s in _SOCIAL_KEYWORDS):
                    btn.click()
                    return True
        except Exception:
            pass
    return False


def _fill_visible_fields(page, cred: dict) -> None:
    """Fill all currently visible auth fields (email, passwords, name)."""
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
        try:
            el = page.get_by_label("email", exact=False).first
            if el.count() > 0 and el.is_visible():
                _type_into(page, el, cred["username"])
        except Exception:
            pass
    for el in page.query_selector_all('input[type="password"]'):
        if el.is_visible():
            _type_into(page, el, cred["password"])
    for name_sel, val in [
        ('input[name*="fName" i], input[id*="first" i], input[name*="firstName" i],'
         'input[placeholder*="first" i]', cred.get("first_name", "")),
        ('input[name*="lName" i], input[id*="last" i], input[name*="lastName" i],'
         'input[placeholder*="last" i]', cred.get("last_name", "")),
    ]:
        if not val:
            continue
        el = page.query_selector(name_sel)
        if el and el.is_visible():
            _type_into(page, el, val)


def _handle_otp_state(page, site: str, cred: dict) -> None:
    """Get OTP from Gmail, fill it, then continue handling whatever page comes next."""
    from ..integrations.gmail_otp import poll_otp, available
    if not available():
        print("[cred] Gmail OTP not available", flush=True)
        return
    try:
        code = poll_otp(timeout_s=1800, sender_hint=site)
        if not code:
            print(f"[cred] OTP timeout for {site}", flush=True)
            return
        print(f"[cred] got OTP code={code!r}, filling now", flush=True)
        if code.startswith("http"):
            page.goto(code, wait_until="domcontentloaded")
            next_state = _observe_until_change(page, "otp_link")
        else:
            filled = _fill_otp_generic(page, code)
            print(f"[cred] OTP fill result: {filled}", flush=True)
            page.wait_for_timeout(500)
            clicked = _click_non_social_submit(page, ("Verify", "Continue", "Submit", "Sign In"))
            print(f"[cred] OTP submit clicked: {clicked}", flush=True)
            next_state = _observe_until_change(page, "otp_submit")
        print(f"[cred] post-OTP state: {next_state}", flush=True)
        # Keep the chain going — Phenom shows password/registration step after OTP
        if next_state not in ("unknown", "otp"):
            _handle_state(page, next_state, cred, site)
    except Exception as e:
        print(f"[cred] _handle_otp_state error: {e}", flush=True)


def _handle_state(page, state: str, cred: dict, site: str) -> None:
    """Act on an observed page state: fill what's now visible, then re-observe."""
    if state == "otp":
        _handle_otp_state(page, site, cred)
    elif state == "verify_email":
        _handle_otp_state(page, site, cred)  # poll_otp returns link or code
        # If we landed on a login form after email verify, fill it
        new_state = _classify_page_state(page)
        if new_state in ("password", "registration"):
            _fill_visible_fields(page, cred)
            page.wait_for_timeout(500)
            _click_non_social_submit(page)
            _observe_until_change(page, "post_verify_login")
    elif state == "password":
        # Email-first: password step appeared — fill password and submit
        for el in page.query_selector_all('input[type="password"]'):
            if el.is_visible():
                _type_into(page, el, cred["password"])
        page.wait_for_timeout(500)
        _click_non_social_submit(page, ("Sign In", "Log In", "Continue", "Submit"))
        _observe_until_change(page, "pw_submit")
    elif state == "registration":
        # Registration fields appeared — fill name + password
        _fill_visible_fields(page, cred)
        page.wait_for_timeout(500)
        _click_non_social_submit(page)
        next_state = _observe_until_change(page, "post_register")
        if next_state in ("otp", "verify_email"):
            _handle_state(page, next_state, cred, site)
    elif state == "oauth":
        print("[cred] OAuth page detected — cannot complete programmatically, going back", flush=True)
        try:
            page.go_back()
            page.wait_for_timeout(2000)
        except Exception:
            pass


def _fill_wall(page, gate: str, cred: dict, site: str = "") -> None:
    """Fill all visible auth fields, submit, then observe and handle the resulting state."""
    try:
        _fill_visible_fields(page, cred)
        page.wait_for_timeout(800)
        clicked = _click_non_social_submit(page)
        if clicked:
            state = _observe_until_change(page, "wall_submit")
            if state not in ("unknown",):
                _handle_state(page, state, cred, site)
    except Exception as e:
        print(f"[cred] _fill_wall error: {e}", flush=True)


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


def _ibm_login(page, cred: dict, original_url: str | None = None) -> None:
    """IBM Security Verify two-step login: IBMid → Continue → password → Sign in."""
    try:
        # Step 1: fill IBMid field (id="uid") and click Continue
        uid = (page.query_selector('input[id="uid"]')
               or page.query_selector('input[name="uid"]')
               or page.query_selector('input[autocomplete="username"]'))
        if uid and uid.is_visible():
            _type_into(page, uid, cred["username"])
            print(f"[ibm] filled IBMid with {cred['username']}", flush=True)
        else:
            print("[ibm] IBMid field not found", flush=True)
            return

        cont = page.query_selector('button[id="continue-button"]') or \
               page.query_selector('button[type="submit"]')
        if not cont:
            try:
                cont = page.get_by_role("button", name="Continue").first
            except Exception:
                pass
        if cont and cont.is_visible():
            cont.click()
            print("[ibm] clicked Continue", flush=True)
            page.wait_for_timeout(3000)
        else:
            print("[ibm] Continue button not found", flush=True)
            return

        # Step 2: password page
        pw = page.query_selector('input[type="password"]')
        if pw and pw.is_visible():
            _type_into(page, pw, cred["password"])
            print("[ibm] filled password", flush=True)
            sign_in = page.query_selector('button[id="signinbutton"]') or \
                      page.query_selector('button[type="submit"]')
            if sign_in and sign_in.is_visible():
                sign_in.click()
                print("[ibm] clicked Sign in", flush=True)
                page.wait_for_timeout(5000)
        else:
            print("[ibm] password field not found after Continue", flush=True)

        print(f"[ibm] after login URL: {page.url}", flush=True)
        if original_url and page.url != original_url:
            page.goto(original_url, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
    except Exception as e:
        print(f"[ibm] login error: {e}", flush=True)


def _ibm_register(page, cred: dict, original_url: str | None = None) -> None:
    """Create a new IBMid account via the 'Create an IBMid' link."""
    try:
        for sel in ['a:has-text("Create an IBMid")', 'a[href*="register"]']:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                print("[ibm] clicked Create an IBMid", flush=True)
                page.wait_for_timeout(3000)
                break

        # Registration form fields
        for field_sel, val in [
            ('input[name="firstName"], input[id*="first" i]', cred.get("first_name", "")),
            ('input[name="lastName"], input[id*="last" i]', cred.get("last_name", "")),
            ('input[name="emailAddress"], input[type="email"]', cred["username"]),
            ('input[name="password"]', cred["password"]),
            ('input[name="confirmPassword"], input[id*="confirm" i]', cred["password"]),
        ]:
            el = page.query_selector(field_sel)
            if el and el.is_visible() and val:
                _type_into(page, el, val)

        page.wait_for_timeout(500)
        submit = page.query_selector('button[type="submit"]')
        if submit and submit.is_visible():
            submit.click()
            print("[ibm] submitted registration form", flush=True)
            page.wait_for_timeout(5000)
        print(f"[ibm] after register URL: {page.url}", flush=True)
    except Exception as e:
        print(f"[ibm] register error: {e}", flush=True)


_IBM_HOSTS = ("login.ibm.com", "w3id.sso.ibm.com", "iam.cloud.ibm.com", "ibm.com")


def _is_ibm_page(page) -> bool:
    """Detect IBM Security Verify by page content (catches UHG SSO redirect)."""
    try:
        txt = (page.query_selector("body") or page).inner_text() or ""
        return "IBMid" in txt or "IBM Security Verify" in txt
    except Exception:
        return False

_LOGIN_TEXTS = [
    "sign in", "log in", "login", "already have an account",
    "existing user", "have an account", "back to login", "returning user",
]
_SIGNUP_TEXTS = [
    "sign up", "register", "create account", "create an account",
    "new user", "don't have an account", "no account", "new here",
    "join now", "get started", "new to",
]
# Keywords that, if present in ANY visible link/button text, aria-label, or title
# on a login/signup wall, indicate an account-free path. Checked as substrings.
_GUEST_KEYWORDS = ["guest", "without account", "without sign", "without log",
                   "without register", "skip sign", "skip log", "skip reg",
                   "no account", "quick apply", "apply directly",
                   "apply as visitor", "one-time", "anonymous",
                   "proceed without", "continue without", "apply without"]


_SOCIAL_KEYWORDS = ("google", "facebook", "linkedin", "github", "twitter", "microsoft", "apple")


def _navigate_to_form(page, link_texts: list[str], label: str) -> bool:
    try:
        sel = "a, button, input[type='button'], input[type='submit']"
        for el in page.query_selector_all(sel):
            if not el.is_visible():
                continue
            text = (el.text_content() or el.get_attribute("value") or "").strip().lower()
            # Skip social-login buttons (e.g. "Sign in with Google")
            if any(s in text for s in _SOCIAL_KEYWORDS):
                continue
            if any(t in text for t in link_texts):
                print(f"[cred] navigating to {label}: {text!r}", flush=True)
                el.click()
                state = _observe_until_change(page, "navigate_form")
                print(f"[cred] after nav click state: {state}", flush=True)
                return True
    except Exception:
        pass
    return False


def _try_guest_apply(page) -> bool:
    """Click any visible link/button that offers an account-free path.

    Checks element text, aria-label, and title — the label can be anything.
    """
    try:
        sel = "a, button, input[type='button'], input[type='submit'], [role='button'], [role='link']"
        for el in page.query_selector_all(sel):
            if not el.is_visible():
                continue
            # Gather all text signals for this element (input uses .value, others use textContent)
            signals = [
                (el.text_content() or el.get_attribute("value") or "").lower(),
                (el.get_attribute("aria-label") or "").lower(),
                (el.get_attribute("title") or "").lower(),
            ]
            combined = " ".join(signals)
            if any(kw in combined for kw in _GUEST_KEYWORDS):
                label = (el.text_content() or "").strip()[:60]
                print(f"[cred] guest path found: {label!r} — clicking", flush=True)
                el.click()
                page.wait_for_timeout(2000)
                return True
    except Exception as _e:
        print(f"[cred] guest apply scan error: {_e!r}", flush=True)
    return False


def _ensure_login_form(page) -> None:
    _navigate_to_form(page, _LOGIN_TEXTS, "login form")


def _ensure_signup_form(page) -> None:
    _navigate_to_form(page, _SIGNUP_TEXTS, "sign-up form")


def provide(page, gate: str, site: str, original_url: str | None = None,
            email: str = "") -> bool:
    """Fill an account/login wall using stored or freshly-generated credentials.

    Flow:
      1. Guest apply available → click it, done (no account needed).
      2. Credentials already stored → go to login form and fill.
      3. No credentials yet → go to REGISTER form, fill, then login.
    """
    if "infosys" in site or "intapidm" in site:
        site = "career.infosys.com"

    # Step 1 — guest apply (always try first; no account needed)
    if _try_guest_apply(page):
        return True
    cred = load_credential(site, label=gate)

    is_new = cred is None
    if cred is None:
        username = _email_on_page(page) or email or _default_email()
        password = generate_password()
        extra = {
            "first_name": os.getenv("CAREER_AGENT_FIRST_NAME", "Rakshit"),
            "last_name": os.getenv("CAREER_AGENT_LAST_NAME", "Singh"),
        }
        # For SPECIALS, save now (they manage their own flow); generic path saves after confirm
        cred = {"username": username, "password": password, "label": gate, **extra}

    # Step 2 / 3 — ATS-specific handlers (they know register vs login distinction)
    _is_special = (any(h in site for h in _IBM_HOSTS) or _is_ibm_page(page)
                   or "darwinbox" in site or "infosys" in site)
    if is_new and _is_special:
        save_credential(site, cred["username"], cred["password"], label=gate,
                        first_name=cred.get("first_name", ""), last_name=cred.get("last_name", ""))

    if any(h in site for h in _IBM_HOSTS) or _is_ibm_page(page):
        if is_new:
            _ibm_register(page, cred, original_url=original_url)
        _ibm_login(page, cred, original_url=original_url)
    elif "darwinbox" in site:
        if is_new:
            _darwinbox_register(page, cred, original_url=original_url)
        _darwinbox_login(page, cred, original_url=original_url)
    elif "infosys" in site:
        if is_new:
            _infosys_register(page, cred, original_url=None)
        _infosys_login(page, cred, original_url=original_url)
    else:
        # Generic path — observation-driven: look at the page, then act.
        if _is_email_first(page):
            # Email-only form visible (no password field yet).
            # Fill email, click Continue, then observe and handle whatever appears.
            print(f"[cred] email-first form detected on {site}", flush=True)
            email_sel = ('input[type="email"], input[name*="email" i], input[id*="email" i],'
                         'input[name*="userName" i]')
            for el in page.query_selector_all(email_sel):
                if el.is_visible():
                    _type_into(page, el, cred["username"])
                    break
            page.wait_for_timeout(500)
            _click_non_social_submit(page, ("Continue", "Next", "Sign In", "Log In", "Submit"))
            state = _observe_until_change(page, "email_first_continue")
            print(f"[cred] after email+Continue: {state}", flush=True)
            # Save credential as soon as the email is accepted (OTP, verify_email, or
            # direct registration all confirm Phenom accepted this email address)
            if is_new and state in ("registration", "otp", "verify_email"):
                save_credential(site, cred["username"], cred["password"],
                                label=gate, first_name=cred.get("first_name", ""),
                                last_name=cred.get("last_name", ""))
                print(f"[cred] saved credential for {site}", flush=True)
            _handle_state(page, state, cred, site)
        elif is_new:
            # Traditional form (email+password together) — need to register first
            print(f"[cred] no stored cred for {site} — navigating to signup", flush=True)
            found = _navigate_to_form(page, _SIGNUP_TEXTS, "sign-up form")
            if not found:
                print(f"[cred] no signup form found on {site} — escalating", flush=True)
                return False
            _fill_wall(page, gate, cred, site=site)
        else:
            # Traditional form, have credentials — login
            _ensure_login_form(page)
            _fill_wall(page, gate, cred, site=site)
    return True
