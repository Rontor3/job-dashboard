"""Reusable Answer Bank for Naukri's chatbot apply.

Precompute grounded answers per intent once, match each incoming question by
meaning (keyword first, then embedding similarity), reuse known answers, and pause
the candidate only for exceptional questions. Pure logic, no browser. Personal
facts come from the stored profile and are NEVER sent to the LLM. Never raises.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from job_dashboard.apply.screening import draft_screening_answer
from job_dashboard.match.embedder import cosine

MATCH_THRESHOLD = 0.60

# Multi-word entries must be checked before their single-word substrings.
SKILL_VOCAB = [
    "machine learning", "deep learning", "computer vision", "time series",
    "power bi", "scikit-learn", "python", "sql", "scala", "spark", "hadoop",
    "tensorflow", "pytorch", "keras", "sklearn", "nlp", "llm", "genai", "aws",
    "azure", "gcp", "docker", "kubernetes", "tableau", "excel", "statistics",
    "java", "ml", "ai", "r",
]

# intent -> (profile key, canonical phrasing). Order = keyword-match priority.
_PERSONAL = [
    ("expected_ctc", "salary_expectation", "what is your expected ctc salary"),
    ("current_ctc", "current_ctc", "what is your current ctc salary"),
    ("notice_period", "notice_period", "what is your notice period"),
    ("willing_to_relocate", "willing_to_relocate", "are you willing to relocate"),
    ("reason_for_change", "reason_for_change", "what is your reason for change"),
    ("location", "location", "what is your current location"),
]
_PERSONAL_KEYWORDS = [
    ("expected_ctc", ("expected ctc", "expected salary", "expected compensation", "expected pay")),
    ("current_ctc", ("current ctc", "current salary", "present ctc", "current compensation", "current pay")),
    ("notice_period", ("notice period", "notice")),
    ("willing_to_relocate", ("relocat",)),
    ("reason_for_change", ("reason for change", "reason for leaving", "reason for switch",
                            "why do you want to change", "why are you looking")),
    ("location", ("current location", "your location", "where are you located",
                   "current city", "based out of")),
    ("total_experience", ("total experience", "years of experience", "work experience",
                           "overall experience", "how many years")),
]


@dataclass
class AnswerResult:
    text: str
    source: str            # "bank" | "profile" | "unanswered"
    needs_user: bool
    flag: str | None = None


@dataclass
class BankEntry:
    intent: str
    phrasing: str
    text: str
    source: str            # "bank" (résumé-derived) | "profile" (stored field)
    vector: object = None


def _mentions(text, skill):
    """Whole-word (not substring) match, so short skills like 'r'/'ai'/'ml'
    don't false-match inside words ('notice pe[r]iod', 'cu[r]rent')."""
    return re.search(r"\b" + re.escape(skill) + r"\b", text) is not None


def _skill_token(ql):
    for s in SKILL_VOCAB:
        if _mentions(ql, s):
            return s
    return None


def _find(bank, intent):
    for e in bank:
        if e.intent == intent:
            return e
    return None


def _draft_skill_answer(skill, job, profile_text, resume_text, llm):
    q = f"How many years of experience do you have with {skill}?"
    try:
        res = draft_screening_answer(job, q, profile_text, None, resume_text, llm=llm)
    except Exception:
        return None
    if res.get("unsupported_company_claims") or "general_fallback" in (res.get("flags") or []):
        return None  # couldn't ground -> no entry -> resolve pauses the candidate
    return (res.get("answer") or "").strip() or None


def build_answer_bank(package, profile_text=None, resume_text="", llm=None, embedder=None):
    package = package or {}
    profile = package.get("profile") or {}
    job = package.get("job") or {}
    if profile_text is None:
        try:
            from job_dashboard.match.profile_text import compose_profile_text
            profile_text = compose_profile_text().text
        except Exception:
            profile_text = ""
    if llm is None:
        try:
            from job_dashboard.letter.draft import make_default_llm
            llm = make_default_llm()
        except Exception:
            llm = None

    entries: list[BankEntry] = []

    yrs = str(profile.get("years_experience") or "").strip()
    if yrs:
        entries.append(BankEntry("total_experience", "total years of work experience", yrs, "profile"))

    blob = f"{profile_text}\n{resume_text}".lower()
    resume_skills = [s for s in SKILL_VOCAB if _mentions(blob, s)]
    for s in resume_skills:
        if llm is None:
            continue
        ans = _draft_skill_answer(s, job, profile_text, resume_text, llm)
        if ans:
            entries.append(BankEntry(f"skill:{s}", f"years of experience with {s}", ans, "bank"))

    for intent, key, phrasing in _PERSONAL:
        val = profile.get(key)
        if key == "willing_to_relocate" and val is not None:
            val = "Yes" if val else "No"
        if val not in (None, ""):
            entries.append(BankEntry(intent, phrasing, str(val), "profile"))

    if embedder is not None:
        for e in entries:
            try:
                e.vector = embedder.encode(e.phrasing)
            except Exception:
                e.vector = None
    return entries


def _keyword_intent(ql):
    for intent, kws in _PERSONAL_KEYWORDS:
        if any(k in ql for k in kws):
            return intent
    return None


def resolve_answer(question, bank, package=None, embedder=None):
    ql = (question or "").strip().lower()
    if not ql:
        return AnswerResult("", "unanswered", True, "exceptional")

    # 1. Skill token — reuse if on résumé, else pause (never auto-answer).
    token = _skill_token(ql)
    if token:
        entry = _find(bank, f"skill:{token}")
        if entry:
            return AnswerResult(entry.text, "bank", False)
        return AnswerResult("", "unanswered", True, "skill_not_on_resume")

    # 2. Keyword intents (personal + total experience).
    intent = _keyword_intent(ql)
    if intent:
        entry = _find(bank, intent)
        if entry:
            return AnswerResult(entry.text, entry.source, False)
        return AnswerResult("", "unanswered", True, "no_stored_value")

    # 3. Semantic paraphrase fallback.
    if embedder is not None and bank:
        try:
            qv = embedder.encode(question)
            best, score = None, -1.0
            for e in bank:
                if e.vector is None:
                    continue
                c = cosine(qv, e.vector)
                if c > score:
                    best, score = e, c
            if best is not None and score >= MATCH_THRESHOLD:
                return AnswerResult(best.text, best.source, False)
        except Exception:
            pass

    # 4. Exceptional.
    return AnswerResult("", "unanswered", True, "exceptional")
