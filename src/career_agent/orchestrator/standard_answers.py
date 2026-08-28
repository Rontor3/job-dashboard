"""Deterministic canonical answers for a few standard application questions.
LLM-free. Returns None to signal "escalate to human" — never a guess."""
from __future__ import annotations

import re

_COUNTRY_YES = re.compile(r"\bindia\b", re.I)
# Full country names are case-insensitive; the 2-letter abbreviations are
# matched CASE-SENSITIVELY (uppercase only) so the pronoun "us"/word "uk" is
# never mistaken for the country (M-2).
_COUNTRY_NO_CI = re.compile(
    r"united states|united kingdom|\bamerica\b|\bcanada\b|\baustralia\b|"
    r"\bgermany\b|\bsingapore\b|\bireland\b|\bnetherlands\b|\beurope\b", re.I)
_COUNTRY_NO_CS = re.compile(r"\bU\.?S\.?A?\.?\b|\bU\.?K\.?\b|\bEU\b")
# A combined "authorized to work … without sponsorship" question is really an
# authorization question — too ambiguous to answer as plain sponsorship.
_COMBINED = re.compile(r"\bauthoriz|\beligib|\bwithout\b", re.I)


def answer(purpose: str, label: str) -> str | None:
    text = label or ""
    if purpose == "visa_sponsorship":
        if _COMBINED.search(text):
            return None                   # combined/ambiguous -> escalate (I-2)
        return "Yes"                      # would need a visa for onsite/relocation
    if purpose == "prior_contact":
        return "No"
    if purpose == "work_authorization":
        yes = _COUNTRY_YES.search(text)
        no = _COUNTRY_NO_CI.search(text) or _COUNTRY_NO_CS.search(text)
        if yes and no:
            return None                   # both jurisdictions named -> escalate (I-1)
        if yes:
            return "Yes"
        if no:
            return "No"
        return None                       # no determinable country -> escalate
    return None
