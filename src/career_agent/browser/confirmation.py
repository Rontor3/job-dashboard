"""Proof that an application really went through.

Clicking Submit is not submitting: a validation error, a captcha or a slow server leaves the form on screen. A submit
counts only when the page shows an application-received confirmation AND the form is gone. Structural, not per site:
the words ("thank you for applying", "application submitted/received/sent") on a page that no longer holds an
application form. The same check recognises a submit the human made by hand on a parked tab."""
from __future__ import annotations

import re

from .clicks import wait

_TEXT_OK = re.compile(
    r"thank you for (applying|your (application|interest))"
    r"|(your )?application (has been |was |is )?(successfully )?(submitted|received|sent|complete(d)?)"
    r"|successfully (submitted|applied)|we(?:'ve| have) received your application"
    r"|you(?:'ve| have)? (just )?applied\b|application sent\b"
    r"|[✓✔]\s*applied\b", re.I)                       # the Apply button turned into a ticked "Applied" (same page, no form)
_TEXT_NO = re.compile(r"not (been )?(submitted|sent)|could not (submit|send)|submission failed|please (correct|fix)|required field|try again", re.I)
MAX_FORM_FIELDS = 3           # a confirmation page may carry a search box or two; an application form carries many

_SIGNALS_JS = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 4 && r.height > 4; };
  const fields = Array.from(document.querySelectorAll('input,select,textarea,[role=combobox]')).filter(vis)
    .filter(e => !['hidden','submit','button','checkbox','radio','search'].includes(e.type) && !/search/i.test((e.getAttribute('aria-label') || e.name || e.placeholder || '')));
  return { text: (document.body && document.body.innerText || '').slice(0, 4000), fields: fields.length, url: location.href };
}"""


def confirmation_from_signals(sig: dict) -> tuple[bool, str]:
    """(confirmed, why) from {text, fields}. Pure."""
    text = sig.get("text") or ""
    m = _TEXT_OK.search(text)
    if not m:
        return False, "no confirmation text"
    if _TEXT_NO.search(text[max(0, m.start() - 200): m.end() + 200]):
        return False, "confirmation text next to an error"
    if (sig.get("fields") or 0) > MAX_FORM_FIELDS:
        return False, f"form still on screen ({sig.get('fields')} fields)"
    return True, f"page says {m.group(0)!r}"


def page_confirmed(page) -> tuple[bool, str]:
    """Check the page (and its frames: a confirmation can render inside an embedded ATS) once."""
    last = (False, "no confirmation text")
    for fr in [page, *[f for f in getattr(page, "frames", []) if f is not getattr(page, "main_frame", None)]]:
        try:
            ok, why = confirmation_from_signals(fr.evaluate(_SIGNALS_JS))
        except Exception:
            continue
        if ok:
            return True, why
        last = (False, why)
    return last


def wait_for_confirmation(page, timeout_s: int = 25, poll_s: float = 1.0) -> tuple[bool, str]:
    """Poll after a submit click until the page confirms or the time is up. Never clicks anything."""
    waited, last = 0.0, (False, "no confirmation text")
    while waited <= timeout_s:
        last = page_confirmed(page)
        if last[0]:
            return last
        try:
            wait(page, int(poll_s * 1000))
        except Exception:
            break
        waited += poll_s
    return last
