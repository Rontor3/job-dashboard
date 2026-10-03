"""Bank and government-ID details never flow through the agent.

A field asking for one (account number, IFSC, card, PAN, Aadhaar, SSN, passport
number, ...) is taken out of the answer ladder before anything runs: it is never
filled from the profile or the question bank, never asked on Telegram or in the
terminal, and never saved to the Answers tab. If the form REQUIRES one, the run
stops with `sensitive_field` and the job waits for you to fill it yourself;
optional ones are simply left blank. Only free-text style fields count — a
yes/no like "Do you have a bank account?" is not a detail.
"""
from __future__ import annotations

import re

_SENSITIVE = re.compile(
    r"\bbank\s*(account|a/c|name|details|branch|statement|code)\b|\baccount\s*(number|no\b|#|holder)"
    r"|\ba/c\s*(no|number)|\bifsc\b|\biban\b|\bswift\s*(/\s*bic|code)|\bbic\b|\brouting\s*(number|no\b)"
    r"|\bsort\s*code\b|\b(credit|debit)\s*card\b|\bcard\s*(number|no\b|holder)|\bcvv\b|\bcvc\b|\bupi\b"
    r"|\bpan\s*(card|number|no\b|id\b|details)|\bpermanent\s+account\s+number|^\s*pan\s*[:*]?\s*$"
    r"|\baadh?aa?r\b|\badhaar\b|\buan\b|\bsocial\s+security\b|\bssn\b|\bnational\s+insurance\b|\bnino\b"
    r"|\btax\s*(id\b|identification)|\btaxpayer\b|\bpassport\s*(number|no\b|#|details)"
    r"|\blicen[cs]e\s*(number|no\b|#)|\bnational\s+(id|identity)\b|\bvoter\s*id\b|\bidentity\s*(card|number)",
    re.I)

# Fields that take a typed/chosen value. Choice questions and uploads are not "a detail".
_NOT_A_VALUE = {"checkbox", "radio", "radio_group", "file", "button"}


def is_sensitive(f) -> bool:
    if getattr(f, "kind", "") in _NOT_A_VALUE:
        return False
    text = f"{getattr(f, 'label', '') or ''} {getattr(f, 'description', '') or ''}"
    return bool(_SENSITIVE.search(text))


def split_sensitive(fields) -> tuple[list, list]:
    """(safe, blocked), each in the original order."""
    safe, blocked = [], []
    for f in fields:
        (blocked if is_sensitive(f) else safe).append(f)
    return safe, blocked
