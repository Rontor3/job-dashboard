"""Deterministic canonical answers for a few standard application questions.
LLM-free. Returns None to signal "escalate to human" — never a guess."""
from __future__ import annotations

import re

_COUNTRY_YES = re.compile(r"\bindia\b", re.I)
_COUNTRY_NO = re.compile(
    r"\b(u\.?\s?s\.?a?\b|united states|america|u\.?k\.?\b|united kingdom|canada|"
    r"australia|germany|singapore|ireland|netherlands|europe|eu)\b", re.I)


def answer(purpose: str, label: str) -> str | None:
    text = label or ""
    if purpose == "visa_sponsorship":
        return "Yes"                      # would need a visa for onsite/relocation
    if purpose == "prior_contact":
        return "No"
    if purpose == "work_authorization":
        if _COUNTRY_YES.search(text):
            return "Yes"
        if _COUNTRY_NO.search(text):
            return "No"
        return None                       # no determinable country -> escalate
    return None
