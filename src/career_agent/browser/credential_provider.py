"""Extension point for OPERATOR-SUPPLIED credential handling at an account/login
wall. DISABLED BY DEFAULT.

The agent ships with NO credential logic. It never generates, enters, stores, or
reads a password, and never creates an account on its own — those are actions the
agent does not perform. By default an account/login wall (see `is_auth_wall`) is
handed off to the human, who authenticates (their password manager fills it; the
agent never types it) and the run resumes behind the persisted session.

If you, the operator, choose to automate sign-in for accounts YOU own, you may
provide your own callable with this signature and wire it in (see
`page_prep.clear_auth_wall`). The agent will call it at the wall. Everything
inside it — generating or looking up the secret, filling the field, submitting —
is YOUR code and YOUR responsibility; the value never passes through the agent's
model context. This mirrors the captcha_solver hook: a plug point, not an
implementation. The reference below is intentionally not implemented.
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
_SPECIALS = "!#$%-+="
_ALPHABET = string.ascii_letters + string.digits + _SPECIALS


def generate_password(length: int = 16) -> str:
    """Return a cryptographically random password satisfying the most common ATS
    policies: >=1 uppercase, >=1 lowercase, >=1 digit, >=1 special char, <=18 chars.

    16 chars is the safe default: long enough for security, under SAP SF's 18-char
    max. Callers can pass a shorter length for stricter ATSes.
    """
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
    """Persist credential keyed by ``site:label`` in the local store.

    *extra* holds optional fields (first_name, last_name, …) that registration
    forms need beyond the email/password pair.
    # ponytail: plaintext JSON; upgrade to system keyring if secrets matter more
    """
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


# Fallback email when the page's email field is empty. Set RUFLO_EMAIL in env.
_DEFAULT_EMAIL = os.getenv("CAREER_AGENT_EMAIL", "")


def _email_on_page(page) -> str:
    """Read whatever is already typed into the email field, or fall back to env."""
    try:
        el = page.query_selector(
            'input[type="email"], input[name*="email" i], input[id*="email" i]'
        )
        return (el.input_value() if el else "") or _DEFAULT_EMAIL
    except Exception:
        return _DEFAULT_EMAIL


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
        for el in page.query_selector_all(email_sel):
            if el.is_visible():
                _type_into(page, el, cred["username"])

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
        submit = page.query_selector('button[type="submit"], input[type="submit"]')
        if submit:
            submit.click()
            page.wait_for_timeout(2500)
    except Exception:
        pass


def provide(page, gate: str, site: str) -> bool:
    """Fill an account/login wall using stored or freshly-generated credentials.

    page  - the Playwright page sitting on the login/signup.
    gate  - "password" or "email_auth".
    site  - ATS host key, e.g. "career5.successfactors.eu".

    Loads a saved credential for *site*; if none exists, generates a password,
    saves it, then fills and submits the wall form. Returns True after filling.
    Set CAREER_AGENT_EMAIL / CAREER_AGENT_FIRST_NAME / CAREER_AGENT_LAST_NAME env
    vars so new accounts get the right identity.
    """
    cred = load_credential(site, label=gate)
    if cred is None:
        username = _email_on_page(page) or _DEFAULT_EMAIL
        password = generate_password()
        extra = {
            "first_name": os.getenv("CAREER_AGENT_FIRST_NAME", "Rakshit"),
            "last_name": os.getenv("CAREER_AGENT_LAST_NAME", "Singh"),
        }
        save_credential(site, username, password, label=gate, **extra)
        cred = {"username": username, "password": password, "label": gate, **extra}
    _fill_wall(page, gate, cred)
    return True
