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
# "Authorized without sponsorship?" conflates two questions — escalate.
# Plain "will you require sponsorship?" is answerable even if it mentions
# "work authorization" as context — only escalate when "without" is present.
_COMBINED = re.compile(r"\bwithout\b|\beligib", re.I)


def answer(purpose: str, label: str) -> str | None:
    text = label or ""
    if purpose == "visa_sponsorship":
        if _COMBINED.search(text):
            return None                   # combined/ambiguous -> escalate (I-2)
        return "Yes"                      # would need a visa for onsite/relocation
    if purpose == "prior_contact":
        return "No"
    if purpose == "phone_type":
        return "Mobile"
    if purpose == "referral_source":
        return "Job Board"
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
    if purpose == "conflict_of_interest":
        return "No"
    if purpose == "file_comment":
        return "Resume"
    return None
