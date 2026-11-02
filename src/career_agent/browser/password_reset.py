"""Recover an account whose saved password the site refuses: Forgot password -> email -> the reset link from Gmail ->
a new generated password -> saved -> back to sign in.

Why: a refusal with the email filled in means the account EXISTS (NatWest Workday 2026-11-02: 'You may have entered
the wrong email address or password' — an account from an earlier attempt, password unknown). Registering again goes
nowhere ('Create Account' returned to Sign In); only a reset gets back in.

Only a link mailed by the SAME site, after the request, is opened (gmail_otp.poll_verify_link). The new password is saved
before it is submitted, so it is never lost; the refused one is kept as ':stale' history (retire_credential)."""
from __future__ import annotations

import time

_FORGOT = ["forgot your password", "forgot password", "forgotten password", "reset password", "reset your password",
           "trouble signing in", "can't sign in", "cannot sign in", "forgot?"]
_SEND = ("Submit", "Reset Password", "Reset", "Send", "Send Email", "Continue", "Request", "Email Me", "Next")
_SAVE = ("Submit", "Reset Password", "Change Password", "Set Password", "Save", "Update", "Continue", "Confirm")


def _settle(page) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(1500)


def _email_box(page, cp):
    boxes = [e for e in page.query_selector_all(cp._EMAIL_ATTR_SEL) if cp._truly_visible(e)]
    if boxes:
        return boxes[0]
    try:
        loc = page.get_by_label("email", exact=False).first
        return loc if loc.count() > 0 and loc.is_visible() else None
    except Exception:
        return None


def reset_password(page, cred: dict, site: str, label: str = "", wait_s: int = 180) -> dict | None:
    """The credential with its new password once the site took it, else None (nothing changed: no Forgot link, no
    email box, Gmail unavailable, or no reset mail from this site within `wait_s`)."""
    from . import credential_provider as cp
    from ..integrations.gmail_otp import available, poll_verify_link
    if not available():
        return None
    back = page.url
    if not cp._navigate_to_form(page, _FORGOT, "password reset"):
        return None
    _settle(page)
    box = _email_box(page, cp)
    if box is None:
        print(f"[cred] {site}: password reset page has no email box", flush=True)
        return None
    asked = int(time.time()) - 30                      # only a mail sent after this request is ours
    cp._type_into(page, box, cred["username"])
    if not cp._click_non_social_submit(page, _SEND):
        print(f"[cred] {site}: could not send the password-reset request", flush=True)
        return None
    print(f"[cred] {site}: password reset requested — waiting for the email", flush=True)
    link = poll_verify_link(site, asked, timeout_s=wait_s, reset=True)
    if not link:
        return None
    page.goto(link, wait_until="domcontentloaded", timeout=30000)
    _settle(page)
    boxes = []
    for _ in range(20):          # Workday draws its new-password form a few seconds after load (NatWest, live 2026-11-02)
        boxes = [e for e in page.query_selector_all('input[type="password"]') if cp._truly_visible(e)]
        if boxes:
            break
        page.wait_for_timeout(1000)
    if not boxes:
        print(f"[cred] {site}: the reset link opened no new-password form", flush=True)
        return None
    new = cp.generate_password()
    for b in boxes:                                    # new password + confirm
        cp._type_into(page, b, new)
    cp.retire_credential(site, label=label)           # the refused one stays as history
    cp.save_credential(site, cred["username"], new, label=label)
    cp._click_non_social_submit(page, _SAVE)
    page.wait_for_timeout(4000)
    print(f"[cred] {site}: new password set and saved", flush=True)
    try:
        page.goto(back, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
    except Exception:
        pass
    return {**cred, "password": new}
