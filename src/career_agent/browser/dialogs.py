"""Dialogs over an application page: read the open one, say what kind it is, and press one of its buttons.

`classify` is pure (unit-tested). The agent-driven harness (job_dashboard/apply/session_steps.py) checks for a dialog
after every step:
- cookie banners and idle "are you still there?" prompts are handled here;
- a sign-in dialog or a captcha is a wall;
- anything else (a referral prompt, a "confirm your location", a pre-apply "I'm ready to apply") goes to the agent with
  its text and buttons.

Nothing here ever presses a submit, sign-up, payment or delete control."""
from __future__ import annotations

import re

_READ_JS = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 40 && r.height > 40 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const shown = e => { const r = e.getBoundingClientRect(); return r.width > 2 && r.height > 2 && getComputedStyle(e).visibility !== 'hidden'; };
  // A dialog element may itself be a zero-size wrapper whose visible box is a fixed child (Headless UI, Radix): it's
  // open when it, or anything in it, has a box.
  const open = d => vis(d) || [...d.querySelectorAll('*')].slice(0, 80).some(vis);
  document.querySelectorAll('[data-jd-dialog]').forEach(e => e.removeAttribute('data-jd-dialog'));
  const all = [...document.querySelectorAll('[role=dialog],[role=alertdialog],[aria-modal=true],dialog[open]')]
    .filter(d => !d.parentElement || !d.parentElement.closest('[role=dialog],[role=alertdialog],[aria-modal=true],dialog[open]'))
    .filter(open);
  if (!all.length) return null;
  const d = all[all.length - 1];                        // the last opened sits on top
  d.setAttribute('data-jd-dialog', '1');                // press() finds this same element
  const name = e => { const t = (e.innerText || '').trim().replace(/\s+/g, ' ');
    return (t.length > 1 ? t : (e.getAttribute('aria-label') || e.value || t || '')).trim(); };
  const buttons = [...d.querySelectorAll('button,a[href],[role=button],input[type=submit],input[type=button]')]
    .filter(shown).map(name).filter(t => t && t.length <= 60);
  const heading = d.querySelector('h1,h2,h3,[role=heading]');
  return {
    label: (d.getAttribute('aria-label') || (heading ? heading.innerText : '') || '').trim().slice(0, 120),
    text: (d.innerText || '').trim().replace(/\n{2,}/g, '\n').slice(0, 700),
    buttons: [...new Set(buttons)].slice(0, 12),
    inputs: d.querySelectorAll('input:not([type=hidden]),textarea,select').length,
    password: !!d.querySelector('input[type=password]'),
  };
}"""

_CAPTCHA = re.compile(r"captcha|verify (that )?you('| a)re (a )?human|are you a robot|security check", re.I)
_LOGIN = re.compile(r"^\s*(log ?in|sign ?in)( window)?\b|\b(sign|log) in to (apply|continue)\b|\bcreate (an |your )?account\b",
                    re.I | re.M)
_CONSENT = re.compile(r"\bcookies?\b|\bconsent\b|privacy preferences", re.I)
_IDLE = re.compile(r"still there|session (is about to|will) (expire|time ?out)|continue working|been inactive|idle", re.I)
# Never pressed from a dialog, whatever the agent asks: those have their own gates (submit) or are walls.
DENY = re.compile(r"\b(submit|send application|apply now and submit|sign ?up|register|create account|log ?in|sign ?in|"
                  r"pay|purchase|buy|delete|withdraw|remove)\b", re.I)


def read(page) -> dict | None:
    """The top visible dialog on the page (main frame), or None."""
    try:
        return page.evaluate(_READ_JS)
    except Exception:
        return None


def classify(d: dict) -> str:
    """captcha | login | consent | idle | apply_step | question."""
    text = f"{d.get('label', '')}\n{d.get('text', '')}"
    if _CAPTCHA.search(text):
        return "captcha"
    if d.get("password") or _LOGIN.search(text):
        return "login"
    if _CONSENT.search(text) and not d.get("inputs"):
        return "consent"
    if _IDLE.search(text):
        return "idle"
    from .page_prep import _best_apply
    if _best_apply([{"name": b} for b in d.get("buttons") or []]) is not None:
        return "apply_step"
    return "question"


def press(page, button: str) -> None:
    """Press the button of that name inside the open dialog. ValueError when refused or not found."""
    if DENY.search(button or ""):
        raise ValueError(f"\"{button}\" can't be pressed from a dialog: submit, sign-in and payment controls have their own gates")
    from .clicks import pace, timeout_ms
    if not read(page):
        raise ValueError("no dialog is open any more")
    dialog = page.locator("[data-jd-dialog]").first
    pace(page)
    for loc in (dialog.get_by_role("button", name=button, exact=True), dialog.get_by_role("link", name=button, exact=True),
                dialog.locator(f"button:has-text({button!r}), a:has-text({button!r})")):
        try:
            if loc.count():
                loc.first.click(timeout=timeout_ms(5000))
                page.wait_for_timeout(1500)
                return
        except Exception:
            continue
    raise ValueError(f"no button \"{button}\" in the dialog")
