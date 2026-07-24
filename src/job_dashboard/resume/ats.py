"""ATS check — parse the final rendered resume PDF as an ATS parser would.

Runs the PDF through ``pdftotext`` (or an injected extractor, for tests) and
scores the extracted plain text on: contact-info presence, JD keyword
coverage, and section reading order — flagging garbled-glyph signs of a
parse-hostile PDF (missing ToUnicode maps, scrambled column extraction).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

Extractor = Callable[[Path], str]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# "Phone-ish": a run of digits (with optional +, spaces, dashes, dots,
# parens as separators) totaling at least 8 digits — enough to distinguish
# a phone number from stray page numbers or dates.
PHONE_RE = re.compile(r"(?:\+?\d[\d\-.\s()]{6,}\d)")

# v1 salient-keyword tokenizer: lowercase words, drop stopwords + short
# (<3 char) tokens. Deliberately simple — real keyword ranking is deferred
# to a later deep-rank pass; this just measures raw JD/resume term overlap.
STOPWORDS = {
    "the", "and", "for", "with", "you", "your", "our", "are", "will",
    "have", "has", "this", "that", "from", "who", "can", "job", "role",
    "work", "team", "years", "year", "experience", "ability", "strong",
    "using", "into", "about", "such", "than", "they", "them", "their",
    "not", "all", "any", "able", "well", "including", "etc", "per",
    "plus", "must", "should", "would", "could", "may", "also", "new",
    "one", "two", "more", "most", "other", "some", "each", "which",
    "what", "when", "where", "how", "why", "then", "there", "here",
    "you'll", "we're", "we'll", "in", "is", "of", "to", "on", "as",
    "an", "be", "or", "at", "by", "it", "we",
}

# Canonical expected top-to-bottom order for a v1 reading-order heuristic.
SECTION_HEADERS = ["experience", "education", "skills"]

REPLACEMENT_CHAR = "�"
# Above this ratio of replacement/non-printable chars, flag likely garbling.
GARBLED_RATIO_THRESHOLD = 0.02


@dataclass
class AtsReport:
    ats_score: int
    contact_ok: bool
    reading_order_ok: bool
    keyword_coverage: float
    missing_keywords: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _default_extract(pdf_path: Path) -> str:
    """Extract plain text from ``pdf_path`` via a real ``pdftotext`` subprocess.

    Plain reading-order mode (no ``-layout``) is used deliberately: most ATS
    parsers flatten multi-column PDFs into logical reading order the same
    way, so this default mirrors that rather than preserving physical
    layout.
    """
    result = subprocess.run(
        ["pdftotext", str(pdf_path), "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z][A-Za-z+#-]*", text.lower())
    return {w for w in words if len(w) >= 3 and w not in STOPWORDS}


def _contact_ok(text: str) -> bool:
    return bool(EMAIL_RE.search(text)) and bool(PHONE_RE.search(text))


def _reading_order_ok(text: str) -> bool:
    lower = text.lower()
    found = [(header, lower.find(header)) for header in SECTION_HEADERS]
    found = [(header, idx) for header, idx in found if idx != -1]
    if len(found) < 2:
        return True
    positions = [idx for _, idx in found]
    return positions == sorted(positions)


def _keyword_coverage(jd_text: str, resume_text: str) -> tuple[float, list[str]]:
    salient = _tokenize(jd_text)
    if not salient:
        return 1.0, []
    resume_tokens = _tokenize(resume_text)
    missing = salient - resume_tokens
    coverage = (len(salient) - len(missing)) / len(salient)
    return coverage, sorted(missing)[:20]


def _garbled_warning(text: str) -> str | None:
    if not text:
        return None
    bad = sum(
        1 for c in text
        if c == REPLACEMENT_CHAR or (not c.isprintable() and c not in "\n\t\r ")
    )
    if bad / len(text) > GARBLED_RATIO_THRESHOLD:
        return "possible garbled glyphs"
    return None


def ats_check(
    pdf_path: Path | str,
    jd_text: str,
    extract: Extractor | None = None,
) -> AtsReport:
    """Run an ATS-style parse of ``pdf_path`` and score it against ``jd_text``."""
    if extract is None:
        extract = _default_extract

    text = extract(Path(pdf_path))

    contact_ok = _contact_ok(text)
    reading_order_ok = _reading_order_ok(text)
    coverage, missing_keywords = _keyword_coverage(jd_text, text)

    warnings: list[str] = []
    garbled = _garbled_warning(text)
    if garbled:
        warnings.append(garbled)

    ats_score = round(contact_ok * 30 + coverage * 50 + reading_order_ok * 20)

    return AtsReport(
        ats_score=ats_score,
        contact_ok=contact_ok,
        reading_order_ok=reading_order_ok,
        keyword_coverage=coverage,
        missing_keywords=missing_keywords,
        warnings=warnings,
    )
