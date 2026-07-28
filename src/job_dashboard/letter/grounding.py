"""Best-effort unsupported-company-claim guard for a drafted cover letter.

``check_grounding`` scans a letter ``body`` for company-specific claims —
dollar/percent figures, funding/round/revenue terms, and capitalized
product-ish phrases — and flags any that are NOT substantiated (as a literal
substring) by ``research.facts``. It does NOT rewrite the letter; it only
surfaces flags for a human to review in the dashboard panel. This is a
second, independent line of defense alongside ``draft.py``'s structural
"skip the llm when research is empty" guarantee — it also catches drift if
an injected/custom ``llm`` ignores its prompt instructions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from job_dashboard.letter.company_research import ResearchBundle

_MONEY_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s?(?:[MmBbKk](?:illion)?)?")
_PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s?%")
_FUNDING_TERM_RE = re.compile(
    r"\b(Series\s+[A-Z]|funding\s+round|funding|valuation|revenue|ARR|IPO|"
    r"acquisition|acquired|raised|round)\b",
    re.IGNORECASE,
)
# Consecutive Capitalized Words -- a crude proxy for a named product/service.
_PRODUCT_PHRASE_RE = re.compile(r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)+)\b")

# Common letter boilerplate that also happens to be Title Case -- excluded so
# ordinary salutations/sign-offs don't get flagged as "company claims".
_BOILERPLATE_CAP_WORDS = {
    "dear", "hiring", "manager", "sincerely", "regards", "best", "thank",
    "you", "team", "hello", "greetings", "sir", "madam", "yours", "truly",
    "cordially", "attn", "attention", "to", "whom", "it", "may", "concern",
    "role", "position", "company", "the", "job", "description", "cover",
    "letter", "your", "name", "date",
}


@dataclass
class GroundingReport:
    """Result of :func:`check_grounding`."""

    unsupported_company_claims: list[str] = field(default_factory=list)


def _facts_text_blob(research: ResearchBundle | None) -> str:
    facts = getattr(research, "facts", None) if research is not None else None
    if not facts:
        return ""
    return " \n".join(getattr(f, "text", "") or "" for f in facts)


def _is_supported(claim: str, facts_blob: str) -> bool:
    return bool(claim) and claim.lower() in facts_blob.lower()


def _is_boilerplate_phrase(phrase: str) -> bool:
    words = phrase.lower().split()
    return bool(words) and all(w in _BOILERPLATE_CAP_WORDS for w in words)


def _collect_claims(body: str) -> list[str]:
    """Company-specific-looking substrings in ``body``, order-preserving,
    deduped case-insensitively.
    """
    claims: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        claim = raw.strip()
        key = claim.lower()
        if claim and key not in seen:
            seen.add(key)
            claims.append(claim)

    for regex in (_MONEY_RE, _PERCENT_RE, _FUNDING_TERM_RE):
        for match in regex.finditer(body):
            add(match.group(0))

    for match in _PRODUCT_PHRASE_RE.finditer(body):
        phrase = match.group(1)
        if _is_boilerplate_phrase(phrase):
            continue
        add(phrase)

    return claims


def check_grounding(
    letter_body: str,
    research: ResearchBundle | None,
    profile_text: str,
) -> GroundingReport:
    """Flag company-specific claims in ``letter_body`` unsupported by
    ``research.facts``. Best-effort, does not rewrite. ``profile_text`` is
    accepted for interface symmetry (candidate-side grounding is a separate
    concern) but is not itself scanned here -- this checker is focused on
    company claims specifically.
    """
    body = letter_body if isinstance(letter_body, str) else ""
    facts_blob = _facts_text_blob(research)

    claims = _collect_claims(body)
    unsupported = [c for c in claims if not _is_supported(c, facts_blob)]
    return GroundingReport(unsupported_company_claims=unsupported)
