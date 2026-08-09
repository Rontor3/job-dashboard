"""Cheap title-based nuisance filter for the deep-rank batch.

Flags jobs whose *title* is clearly outside a data-science / ML / software
career, so the batch can auto-mark them Poor Fit without spending an LLM call.
Deliberately CONSERVATIVE: only obviously off-target roles (design, teaching,
healthcare, sales, ops, trades). Software-adjacent noise (Java dev, QA, project
manager) is intentionally NOT filtered here — the LLM judge scores those, so we
never wrongly drop a borderline-relevant role.
"""
import re

# Whole-word (or phrase) markers of an off-target role. Matched case-insensitively
# with word boundaries so "designer" doesn't hit "design engineer", etc.
NUISANCE_TERMS = (
    "graphic designer", "ux designer", "ui designer", "visual designer",
    "motion designer", "interior designer", "fashion designer", "designer",
    "professor", "lecturer", "teacher", "faculty", "tutor", "principal teacher",
    "nurse", "physician", "surgeon", "doctor", "dentist", "pharmacist",
    "receptionist", "accountant", "cashier", "bookkeeper", "auditor",
    "driver", "warehouse", "electrician", "plumber", "welder", "carpenter",
    "chef", "cook", "waiter", "barista", "housekeeping", "security guard",
    "sales executive", "sales manager", "salesperson", "business development",
    "telecaller", "telesales", "bpo", "voice process", "customer support",
    "customer service", "recruiter", "talent acquisition", "human resources",
    "hr executive", "hr manager", "content writer", "copywriter",
    "video editor", "social media", "seo executive", "digital marketing",
)
_PATTERNS = [(t, re.compile(r"\b" + re.escape(t) + r"\b")) for t in NUISANCE_TERMS]


def nuisance_match(title):
    """Return the matched nuisance term if the title is off-target, else None."""
    t = (title or "").lower()
    for term, pat in _PATTERNS:
        if pat.search(t):
            return term
    return None


# POSITIVE relevance gate for keyword-blind dump sources (remoteok fetches its
# whole board; remotive's search is loose). Only titles in the ML/AI/DS family
# pass — everything else ("Sales Jedi", "Quality Engineer", "Nurse") is dropped
# at ingest. Kept broad enough not to miss real target roles.
_TARGET_RE = re.compile(
    r"\b("
    r"machine learning|ml engineer|ml scientist|ml ops|mlops|"
    r"a\.?i\.? engineer|ai/ml|ml/ai|artificial intelligence|"
    r"data scientist|data science|data engineer|deep learning|neural network|"
    r"nlp|natural language|llm|large language model|generative ai|genai|"
    r"applied scientist|research scientist|computer vision|"
    r"recommendation system|ml platform|ai platform|ml infrastructure"
    r")\b",
    re.IGNORECASE,
)
# bare "ai"/"ml" as standalone tokens (e.g. "AI Engineer", "ML Lead")
_TARGET_TOKEN_RE = re.compile(r"(?:^|[\s\-/(])(ai|ml)(?:[\s\-/)]|$)", re.IGNORECASE)


def is_target_role(title):
    """True if the title is in the candidate's ML/AI/DS target family."""
    t = title or ""
    return bool(_TARGET_RE.search(t) or _TARGET_TOKEN_RE.search(t))
