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
