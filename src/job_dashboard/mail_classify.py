"""Classify a company's email about a job we applied to.

Categories: acknowledgement | assessment | interview | offer | rejected | other.
The local LLM decides (the email text goes to the local model only); keyword
rules answer when it is down or returns something unusable. Never raises.
"""
from __future__ import annotations

import json
import re

CATEGORIES = ("acknowledgement", "assessment", "interview", "offer", "rejected", "other")
_BODY_CHARS = 3000

# Checked in order: a rejection often mentions "interview", an offer mentions "round".
_RULES = (
    ("rejected", ("regret to inform", "not moving forward", "not be moving forward", "will not be proceeding",
                  "decided to move forward with other", "unfortunately", "not selected", "not been shortlisted",
                  "unable to offer you", "other candidates")),
    ("offer", ("pleased to offer", "offer letter", "excited to offer", "offer of employment", "extend an offer")),
    ("assessment", ("assessment", "coding test", "hackerrank", "codility", "take-home", "take home", "assignment")),
    ("interview", ("interview", "schedule a call", "schedule a conversation", "next round", "technical round",
                   "hr round", "round 1", "round 2", "round 3", "discussion with", "meet the team")),
    ("acknowledgement", ("received your application", "thank you for applying", "thanks for applying",
                         "application has been received", "application submitted", "successfully applied")),
)
_ORDINAL = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
_ROUND = re.compile(r"\b(?:round|stage)\s*(?:#|no\.?\s*)?(\d)\b|\b(first|second|third|fourth|fifth)\s+(?:round|stage|interview)", re.I)


def _round(text: str) -> int | None:
    # Last mention wins: "cleared round 1, the second round is ..." -> 2.
    found = None
    for m in _ROUND.finditer(text):
        found = int(m.group(1)) if m.group(1) else _ORDINAL[m.group(2).lower()]
    return found


def keyword_classify(subject: str, body: str) -> dict:
    text = f"{subject}\n{body}".lower()
    for category, words in _RULES:
        if any(w in text for w in words):
            return {"category": category, "round": _round(text) if category == "interview" else None,
                    "summary": (subject or "")[:120], "by": "rules"}
    return {"category": "other", "round": None, "summary": (subject or "")[:120], "by": "rules"}


_PROMPT = """You sort job-application emails. I applied to "{title}" at "{company}".

Email subject: {subject}
Email body:
{body}

Answer with ONE JSON object and nothing else:
{{"category": "<one of: acknowledgement, assessment, interview, offer, rejected, other>",
  "round": <interview round number if the email says which round, else null>,
  "summary": "<one short sentence: what they want from me or what they decided>"}}"""


def classify(llm, subject: str, body: str, company: str = "", title: str = "") -> dict:
    if llm is not None:
        try:
            raw = llm(_PROMPT.format(title=title, company=company, subject=subject, body=(body or "")[:_BODY_CHARS]))
            m = re.search(r"\{.*\}", raw or "", re.S)
            data = json.loads(m.group(0)) if m else {}
            if data.get("category") in CATEGORIES:
                rnd = data.get("round")
                return {"category": data["category"], "by": "llm",
                        "round": rnd if isinstance(rnd, int) and rnd >= 1 else None,
                        "summary": str(data.get("summary") or "")[:200]}
        except Exception:
            pass
    return keyword_classify(subject, body)
