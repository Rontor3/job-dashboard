"""Ollama adapter producing :class:`LlmProposal` objects for keyword_map.

``make_ollama_llm`` returns an ``LlmFn`` (see ``keyword_map.LlmFn``) that
prompts a local Ollama model (default ``qwen2.5:14b``) to truthfully reword
one resume bullet per salient, uncovered JD keyword. This module NEVER
enforces integrity itself — ``keyword_map._integrity_violation`` re-validates
every proposal this returns against the block's own source text. The prompt
built here only *asks* the model not to fabricate; that's a courtesy, not a
guarantee (see ``keyword_map`` module docstring for the full control stack).

Every failure mode — HTTP error, non-JSON ``resp["response"]``, a malformed
or missing field, an unreachable host — is caught per-keyword and simply
skips that keyword. This function never raises.
"""

from __future__ import annotations

import json
import os
from typing import Callable

from job_dashboard.resume.keyword_map import LlmProposal, extract_keywords
from job_dashboard.resume.segments import Segment

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:14b"

# Bound on how many JD keywords we'll spend model calls on per invocation.
_MAX_KEYWORDS = 8

# Bound on how many keywords extract_jd_keywords returns.
_MAX_JD_KEYWORDS = 15

PostFn = Callable[[str, dict], dict]


def _default_post(url: str, json_body: dict) -> dict:
    import requests  # lazy import: only needed when actually calling Ollama

    return requests.post(url, json=json_body, timeout=60).json()


def _covered_tokens(segments: list[Segment]) -> set[str]:
    """Lowercased keyword tokens already present in some segment's own text."""
    covered: set[str] = set()
    for seg in segments:
        covered |= set(extract_keywords(seg.text))
    return covered


_JD_KEYWORD_SYSTEM_PROMPT = (
    "Extract the concrete technical skills, tools, frameworks, and "
    "technologies explicitly required in this job description. Return "
    'ONLY JSON {"keywords": ["..."]}. Only real tech terms (languages, '
    "libraries, platforms, tools, methods) — NOT soft skills, company "
    "names, years-of-experience, or generic words."
)


def extract_jd_keywords(
    jd_text: str,
    post: PostFn | None = None,
    model: str | None = None,
    host: str | None = None,
) -> list[str]:
    """Extract clean technical JD keywords via a single Ollama call.

    This is the fix for the actual keyword SOURCE the rephrasing LLM was
    starved of: plain regex tokenization of a job description (see
    ``keyword_map.extract_keywords``) surfaces whatever tokens happen to
    be capitalized-looking or punctuation-adjacent — "work.", "rga" — not
    real tech terms. Asking the model to name the concrete skills/tools/
    frameworks it sees gives a clean, salient list instead.

    Returns a lowercased, deduped (order-preserving), length-capped
    (``_MAX_JD_KEYWORDS``) list of keyword strings. ANY failure — HTTP
    error, unreachable host, non-JSON ``resp["response"]``, a missing or
    malformed ``keywords`` field — is caught and this returns ``[]``. This
    function NEVER raises; callers should treat ``[]`` as "extraction
    unavailable" and fall back to ``keyword_map.extract_keywords(jd_text)``.
    """
    resolved_host = host or os.getenv("OLLAMA_HOST", DEFAULT_HOST)
    resolved_model = model or os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
    post_fn = post or _default_post
    url = f"{resolved_host}/api/generate"

    try:
        body = {
            "model": resolved_model,
            "prompt": (
                _JD_KEYWORD_SYSTEM_PROMPT
                + f"\n\nJob description:\n{jd_text}\n\n"
                "Return the JSON object now."
            ),
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }
        resp = post_fn(url, body)
        parsed = json.loads(resp["response"])
        raw_keywords = parsed.get("keywords", [])
        if not isinstance(raw_keywords, list):
            return []

        seen: list[str] = []
        seen_set: set[str] = set()
        for kw in raw_keywords:
            if not isinstance(kw, str):
                continue
            cleaned = kw.strip().lower()
            if not cleaned or cleaned in seen_set:
                continue
            seen_set.add(cleaned)
            seen.append(cleaned)
            if len(seen) >= _MAX_JD_KEYWORDS:
                break
        return seen
    except Exception:
        # Non-JSON response, missing/malformed "keywords" field, HTTP
        # error, unreachable host -> extraction unavailable, never raise.
        return []


def _build_system_prompt() -> str:
    return (
        "You are rewording ONE resume bullet so it truthfully surfaces a "
        "job-description keyword. Rules:\n"
        "1. NEVER invent or imply a tool, library, framework, or skill that "
        "is not already present in the bullet's own text below.\n"
        "2. Keep every real tool/skill already named in the bullet.\n"
        "3. If there is no truthful way to connect the keyword to this "
        "bullet, return an empty string for proposed_text.\n"
        "Respond with ONLY a JSON object with exactly two keys: "
        '"proposed_text" (string) and "confidence" (one of '
        '"exact-synonym", "equivalent", "transferable").'
    )


def _build_user_prompt(segment: Segment, jd_keyword: str) -> str:
    return (
        f"Bullet text:\n{segment.text}\n\n"
        f"Job description keyword to surface (if truthful): {jd_keyword}\n\n"
        "Return the JSON object now."
    )


def _salient_keywords(segments: list[Segment], jd_text: str) -> list[str]:
    """Crude fallback: JD keywords (raw tokenization) not already present
    verbatim in any block's own text. Only used when ``extract_jd_keywords``
    can't produce a clean list (e.g. Ollama unreachable) — see ``llm``
    below, where the clean extraction is tried first.
    """
    covered = _covered_tokens(segments)
    salient = [kw for kw in extract_keywords(jd_text) if kw not in covered]
    return salient[:_MAX_KEYWORDS]


def _best_matching_segment(segments: list[Segment], jd_keyword: str) -> Segment | None:
    """Segment whose own text+tags share the most salient tokens with the
    rest of the JD context around ``jd_keyword`` — here, simply the segment
    whose tags/text tokens most overlap the keyword itself, falling back to
    the first segment when nothing overlaps (still a valid reword target).
    """
    if not segments:
        return None

    best_seg = segments[0]
    best_score = -1
    for seg in segments:
        seg_tokens = set(extract_keywords(seg.text)) | {t.lower() for t in seg.tags}
        score = 1 if jd_keyword in seg_tokens else 0
        # Tie-break toward segments with generally larger tag/keyword overlap
        # with the keyword's own token, then keep first-seen on exact ties.
        if score > best_score:
            best_score = score
            best_seg = seg
    return best_seg


def make_ollama_llm(
    post: PostFn | None = None,
    model: str | None = None,
    host: str | None = None,
) -> Callable[[list[Segment], str], list[LlmProposal]]:
    """Build an ``LlmFn`` backed by a local Ollama ``/api/generate`` call.

    ``post(url, json_body) -> dict`` defaults to a real ``requests.post``
    call; tests inject a fake. ``model``/``host`` default to
    ``OLLAMA_MODEL``/``OLLAMA_HOST`` env vars, then hardcoded defaults.
    """
    resolved_host = host or os.getenv("OLLAMA_HOST", DEFAULT_HOST)
    resolved_model = model or os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
    post_fn = post or _default_post
    url = f"{resolved_host}/api/generate"

    def llm(segments: list[Segment], jd_text: str) -> list[LlmProposal]:
        proposals: list[LlmProposal] = []

        # Clean tech keywords first (the actual keyword SOURCE fix) — a
        # crude regex tokenization of jd_text surfaces junk ("work.",
        # "rga") that no bullet can ever be truthfully reworded around,
        # which is why rewording used to silently produce ~0 proposals.
        # Falls back to the old crude tokenization only when extraction
        # itself is unavailable (e.g. Ollama down).
        extracted = extract_jd_keywords(
            jd_text, post=post_fn, model=resolved_model, host=resolved_host
        )
        if extracted:
            covered = _covered_tokens(segments)
            keywords = [kw for kw in extracted if kw not in covered][:_MAX_KEYWORDS]
        else:
            keywords = _salient_keywords(segments, jd_text)

        for jd_keyword in keywords:
            try:
                seg = _best_matching_segment(segments, jd_keyword)
                if seg is None:
                    continue

                body = {
                    "model": resolved_model,
                    "prompt": (
                        _build_system_prompt()
                        + "\n\n"
                        + _build_user_prompt(seg, jd_keyword)
                    ),
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.2},
                }

                resp = post_fn(url, body)
                parsed = json.loads(resp["response"])

                proposed_text = parsed.get("proposed_text", "")
                confidence = parsed.get("confidence", "")

                if not proposed_text:
                    continue

                proposals.append(
                    LlmProposal(
                        block_id=seg.id,
                        jd_keyword=jd_keyword,
                        proposed_text=proposed_text,
                        confidence=confidence,
                    )
                )
            except Exception:
                # Any HTTP error, missing key, or malformed JSON for this
                # keyword -> skip it and keep going. Never raise.
                continue

        return proposals

    return llm
