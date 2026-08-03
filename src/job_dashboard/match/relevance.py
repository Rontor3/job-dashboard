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
