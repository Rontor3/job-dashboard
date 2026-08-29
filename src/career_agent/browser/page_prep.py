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
