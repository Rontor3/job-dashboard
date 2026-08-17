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
import re
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
        "1. NEVER invent or imply a tool, library, framework, or specific "
        "product/skill that is not already present in the bullet's own "
        "text below.\n"
        "2. Keep every real tool/skill already named in the bullet.\n"
        "3. If the bullet's own work is an exact synonym or a direct "
        "equivalent of the keyword, reword the bullet to surface that and "
        'set confidence to "exact-synonym" or "equivalent".\n'
        "4. If the bullet does NOT show the same thing but DOES show a "
        "genuinely ADJACENT capability to the keyword — real transferable "
        "work, not a coincidence — rewrite the bullet to make that "
        "adjacency explicit. REUSE the candidate's own real terms already "
        "in the bullet plus generic descriptive connector words (e.g. "
        '"agent", "orchestration", "workflow", "pipeline"). Do NOT '
        "introduce any specific product, tool, or framework name that is "
        'not already in the bullet. Set confidence to "transferable".\n'
        "5. If the keyword names a specific tool or product and the "
        "bullet demonstrates no genuinely adjacent capability for it "
        "(e.g. a specific streaming/database/infra product the candidate "
        "never used), return an empty string for proposed_text — it "
        "becomes an honest gap. Do not force a connection that isn't "
        "real.\n"
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
    """Segment whose own text+tags best overlap ``jd_keyword``, falling
    back to the first segment when nothing overlaps at all (still a valid
    reword target).

    Multi-word JD keywords (e.g. "agent frameworks") are split into their
    own salient words via ``extract_keywords`` so each word is scored
    independently — a keyword doesn't need to appear as one exact phrase
    in a block to be considered relevant.

    Two match strengths, deterministic and still simple:
    - exact token match (keyword word == a segment token/tag) scores 2;
    - partial/substring overlap in EITHER direction (e.g. keyword word
      "agent" is a substring of segment token "multi-agent", or vice
      versa) scores 1. This is what lets a segment genuinely about
      "multi-agent architecture" / "multi-agent orchestration" surface as
      the best match for a JD's "agent frameworks", without any fuzzy/ML
      matching — plain substring containment on already-tokenized words.

    Ties keep the first segment with the highest score seen so far (score
    comparison is strict ``>``), so segment order in the input list is the
    deterministic tie-break, same as before this function scored partial
    overlap.
    """
    if not segments:
        return None

    keyword_words = extract_keywords(jd_keyword) or [jd_keyword.lower()]

    best_seg = segments[0]
    best_score = -1
    for seg in segments:
        seg_tokens = set(extract_keywords(seg.text)) | {t.lower() for t in seg.tags}
        score = 0
        for word in keyword_words:
            if word in seg_tokens:
                score += 2
                continue
            if any(
                len(tok) >= 3 and (word in tok or tok in word)
                for tok in seg_tokens
            ):
                score += 1
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
                    "options": {"temperature": 0.1},
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


# A number token INCLUDING its unit/context (leading currency, trailing % or
# scale word) — so "20%" and "$20" are DIFFERENT tokens and one can't ground the
# other. Grounding is unit-aware, not just bare-digit.
_NUM_RE = re.compile(r"(?:[₹$€£]\s*)?\d[\d.,]*\s*(?:%|x|k|m|bn|cr|lpa|lakh|lakhs|million|billion)?", re.I)


def _norm(tok):
    return re.sub(r"[,\s]+", "", tok).lower().rstrip(".")


def _supported_numbers(text):
    return {_norm(m) for m in _NUM_RE.findall(text or "") if any(c.isdigit() for c in m)}


def _ground_bullet(b, allowed):
    def repl(m):
        return m.group(0) if _norm(m.group(0)) in allowed else "[add number]"
    return _NUM_RE.sub(repl, b)


def _strip_unsupported_numbers(b, allowed):
    """Drop (not placeholder) any number token not present in the user's
    own source text. User chose "only use numbers I typed": an ungrounded
    figure is removed and the surrounding whitespace collapsed."""
    def repl(m):
        return m.group(0) if _norm(m.group(0)) in allowed else ""
    out = _NUM_RE.sub(repl, b)
    out = re.sub(r"\s+([,.;:])", r"\1", out)      # tidy space left before punctuation
    return re.sub(r"\s{2,}", " ", out).strip()


# The AI-tell words/phrases that trip content detectors and read as "written by
# a bot". Swapped for plain equivalents (or removed) after generation.
_AI_SWAPS = [
    (re.compile(r"\bleverag(?:ed|ing|es|e)\b", re.I), "used"),
    (re.compile(r"\butiliz(?:ed|ing|es|e)\b", re.I), "used"),
    (re.compile(r"\bspearhead(?:ed|ing|s)?\b", re.I), "led"),
    (re.compile(r"\borchestrat(?:ed|ing|es|e)\b", re.I), "ran"),
    (re.compile(r"\bfacilitat(?:ed|ing|es|e)\b", re.I), "enabled"),
    # Pompous verbs AI/ATS detectors flag on sight (even when the candidate
    # typed them in their own notes) — swapped for the plain thing they mean.
    (re.compile(r"\barchitect(?:ed|ing|s)?\b", re.I), "designed"),
    (re.compile(r"\bproductioni[sz](?:ed|ing|es|e)\b", re.I), "deployed"),
    (re.compile(r"\bstreamlin(?:ed|ing|es|e)\b", re.I), "simplified"),
    (re.compile(r"\bin order to\b", re.I), "to"),
    (re.compile(r"\ba wide (?:range|variety) of\b", re.I), "several"),
]
# Filler words that add nothing and read as AI padding — deleted outright.
_AI_FILLER = re.compile(
    r"\b(?:successfully|seamlessly|robust|comprehensive|cutting[- ]edge|"
    r"state[- ]of[- ]the[- ]art|innovative|significantly|effectively|"
    r"efficiently|meticulously|various|numerous)\s+",
    re.I,
)


def _natural_bullet(b):
    """De-AI a bullet: swap tell-tale verbs for plain ones, drop filler,
    replace em/en dashes with commas, tidy spacing. Deterministic and
    conservative — meaning is preserved."""
    b = b.replace("—", ", ").replace(" – ", ", ").replace(" -- ", ", ")
    for pat, repl in _AI_SWAPS:
        b = pat.sub(repl, b)
    b = _AI_FILLER.sub("", b)
    b = re.sub(r"^\s*[a-z]", lambda m: m.group(0).upper(), b)  # recapitalize if filler was first word
    b = re.sub(r"\s+([,.;:])", r"\1", b)
    return re.sub(r"\s{2,}", " ", b).strip()


# One or two real bullets from the candidate's own résumé, used as a voice
# anchor so generated lines match how THEY write, not generic AI phrasing.
_VOICE_EXEMPLARS = (
    "Built a dynamic mapper using AWS Lambda and DynamoDB for daily updated marking of historical fraud.\n"
    "Backtested the strategy on the last 5 years and got 4% excess XIRR over the actual portfolio."
)


def generate_bullets(heading, details, llm=None, n=3):
    """Turn a heading + rough ``details`` notes into ``n`` plain resume
    bullets via the local LLM. Foregrounds the concrete tech stack and uses
    ONLY numbers that appear in ``details`` — any other figure the model
    emits is stripped by ``_strip_unsupported_numbers`` (grounding, no
    fabrication, no placeholder). Returns ``[]`` on empty input or any
    failure; never raises."""
    try:
        if not (details and str(details).strip()):
            return []
        if llm is None:
            from job_dashboard.letter.draft import make_default_llm
            llm = make_default_llm()
        prompt = (
            f"Turn the rough notes below into exactly {n} résumé bullet points for "
            f"\"{heading or 'this work'}\".\n\n"
            "COVERAGE IS THE PRIORITY. Use EVERY note. If there are more notes than "
            "bullets, combine related notes into one bullet — but never drop a fact, a "
            "number, or a tool the notes mention. Keep every concrete number and every "
            "technology name exactly as written in the notes.\n\n"
            "Write them the way a real engineer types their own résumé — plain, "
            "specific, factual. They must NOT look AI-written (recruiters and AI "
            "detectors reject that instantly).\n\n"
            "Match this person's actual résumé voice:\n"
            f"{_VOICE_EXEMPLARS}\n\n"
            "Rules:\n"
            "- Each bullet is ONE line, roughly 16-30 words — long enough to carry the "
            "real detail (what was built, how, the tech, the number). Don't pad; don't "
            "strip substance.\n"
            "- Start each bullet with a plain, VARIED past-tense verb: Built, Designed, "
            "Deployed, Automated, Cut, Wrote, Trained, Shipped, Mapped, Scored. Never "
            "reuse the same opener twice.\n"
            "- NEVER use these (AI/ATS tells): Architected, Productionized, Leveraged, "
            "Utilized, Spearheaded, Orchestrated, Streamlined, seamlessly, robust, "
            "cutting-edge, state-of-the-art, comprehensive, innovative, 'in order to', "
            "'responsible for', 'successfully', 'various', em-dashes (—), marketing "
            "adjectives.\n"
            "- Use ONLY numbers that appear in the notes. Never invent a metric.\n"
            "- Plain sentences only: no labels, no headings, no preamble, no leading "
            "dash or bullet marker.\n\n"
            f"NOTES:\n{str(details).strip()[:1500]}\n\n"
            f"Output exactly {n} lines, one bullet per line."
        )
        out = llm(prompt)
        allowed = _supported_numbers(details)
        bullets = []
        for line in (out if isinstance(out, str) else "").splitlines():
            line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
            if not line:
                continue
            grounded = _natural_bullet(_strip_unsupported_numbers(line, allowed))
            if grounded:
                bullets.append(grounded)
            if len(bullets) >= n:
                break
        return bullets
    except Exception:
        return []


# A real IMPACT metric: a number that carries a unit (%, currency, scale word,
# man-hours, latency). The unit is REQUIRED — so bare years (2024), plain
# counts (500 on its own) and lone decimals (0.6) are NOT matched/bolded.
_METRIC_RE = re.compile(
    r"(?<![\w*])("
    r"[₹$€£]\s?\d[\d.,]*"                                   # currency: $20, ₹16
    r"|\d[\d.,]*\s?%"                                        # percent: 30%
    r"|\d[\d.,]*\s?(?:x|k|m|bn|cr|lpa|lakhs?|million|billion|"
    r"man-?hours?|hours?|hrs?|seconds?|secs?|minutes?|mins?)\b"  # number + real unit
    r")(?![\w*])",
    re.I,
)


# Generic words the model sometimes returns as "keywords" — never bold these,
# they aren't real technologies and clutter the résumé.
_HL_STOP = {
    "developed", "built", "constructed", "implemented", "designed", "created",
    "used", "using", "developed a", "model", "models", "pipeline", "system",
    "systems", "algorithm", "formula", "data", "api", "apis", "metrics",
    "engagement metrics", "engagement", "translation", "agent", "queries",
    "matching", "scoring", "reconciliation", "embeddings", "embedding",
    "experience", "planning", "conversational", "adaptive", "recall",
    "accuracy", "f1 score", "precision", "latency",
}


def _bold_span(text, phrase):
    """Bold the first occurrence of ``phrase`` (case-insensitive) that is not
    already inside a ``**...**`` span. Returns text unchanged if not found."""
    if not phrase or len(phrase) < 2:
        return text
    pat = re.compile(r"(?<!\*)" + re.escape(phrase) + r"(?!\*)", re.I)
    return pat.sub(lambda m: f"**{m.group(0)}**", text, count=1)


def highlight_bullets(bullets, llm=None):
    """Return ``bullets`` with technical keywords and impact metrics wrapped in
    ``**bold**`` — WITHOUT changing any wording or structure. The model only
    NAMES phrases already present; the ``**`` are applied deterministically by
    substring, so a bullet's words can never change. Numbers with a unit/%%
    are bolded deterministically as a backstop. Returns [] / originals safely
    on any failure; never raises."""
    items = [str(b) for b in (bullets or []) if b and str(b).strip()]
    if not items:
        return []
    phrases = []
    try:
        if llm is None:
            from job_dashboard.letter.draft import make_default_llm
            llm = make_default_llm()
        joined = "\n".join(items)
        prompt = (
            "List ONLY the concrete named technologies in the text below — tools, "
            "libraries, frameworks, programming languages, cloud services, "
            "databases, platforms — exactly as written, comma-separated.\n"
            "Do NOT list: generic words (e.g. 'recall', 'model', 'pipeline', "
            "'accuracy', 'F1 score'), metrics, numbers, years, job titles, or "
            "company names. Only real product/technology names literally present.\n\n"
            f"{joined[:1500]}\n\nList:"
        )
        out = llm(prompt)
        phrases = [p.strip() for p in re.split(r"[,\n;]", out if isinstance(out, str) else "") if p.strip()]
    except Exception:
        phrases = []

    out_items = []
    for b in items:
        low = b.lower()
        result = _METRIC_RE.sub(
            lambda m: f"**{m.group(1)}**" if any(c.isdigit() for c in m.group(1)) else m.group(0),
            b,
        )
        for ph in phrases:
            pl = ph.lower().strip()
            if pl in _HL_STOP:
                continue
            if any(c.isdigit() for c in ph) and not any(c.isalpha() for c in ph):
                continue  # a bare number is not a tech keyword
            if 2 <= len(ph) <= 40 and pl in low:
                result = _bold_span(result, ph)
        out_items.append(result)
    return out_items


def _norm_skill(s):
    return re.sub(r"[^a-z0-9+.#]", "", str(s or "").lower())


def suggest_skills(context, existing=None, llm=None, max_n=12):
    """Suggest concrete skills/tools the candidate demonstrably USED in their
    own experience + project text (``context``) but hasn't yet listed in
    ``existing``. Grounded: every suggestion must literally appear in
    ``context`` — nothing is invented. Returns a deduped list (<= max_n) of
    skill strings, or ``[]`` on empty input / any failure. Never raises."""
    try:
        if not (context and str(context).strip()):
            return []
        if llm is None:
            from job_dashboard.letter.draft import make_default_llm
            llm = make_default_llm()
        ctx = str(context)
        ctx_l = ctx.lower()
        existing_norm = {_norm_skill(s) for s in (existing or [])}
        prompt = (
            "From the candidate's own experience and project text below, list the "
            "concrete technical skills, tools, frameworks, languages, and platforms "
            "they actually used. Only terms that literally appear in the text — do "
            "NOT infer or add anything not written there.\n"
            f"Already listed (skip these): {', '.join(existing or []) or '(none)'}\n\n"
            f"TEXT:\n{ctx[:2500]}\n\n"
            "Reply as a plain comma-separated list of skill terms, nothing else."
        )
        out = llm(prompt)
        raw = re.split(r"[,\n;]", out if isinstance(out, str) else "")
        seen, result = set(), []
        for term in raw:
            term = re.sub(r"^[\s\-*•\d.)]+", "", term).strip()
            if not term or len(term) > 40:
                continue
            norm = _norm_skill(term)
            # Grounding: keep only terms actually present in the candidate's
            # text and not already listed / already suggested.
            if not norm or norm in existing_norm or norm in seen:
                continue
            if term.lower() not in ctx_l:
                continue
            seen.add(norm)
            result.append(term)
            if len(result) >= max_n:
                break
        return result
    except Exception:
        return []


def regenerate_block(kind, title, bullets, jd_text, profile_text, llm=None, n=2):
    try:
        if llm is None:
            from job_dashboard.letter.draft import make_default_llm
            llm = make_default_llm()
        prompt = (
            f"Rewrite this résumé block as {n} alternatives, each tuned toward the JD.\n\n"
            "Write like a real engineer typing their own résumé — plain and factual, "
            "NOT AI-sounding (recruiters and AI detectors reject that instantly). "
            "Match this person's voice:\n"
            f"{_VOICE_EXEMPLARS}\n\n"
            "Rules: 1-3 dry, specific bullets per alternative; write PLAIN text with "
            "NO markdown and NO ** bold (bolding is applied separately); keep ONLY "
            "numbers already in the source (never invent). "
            "BANNED words: leveraged, utilized, spearheaded, seamlessly, robust, "
            "cutting-edge, comprehensive, innovative, streamline, 'in order to', "
            "'responsible for', 'successfully', em-dashes (—).\n\n"
            f"BLOCK ({kind}) {title}:\n" + "\n".join(f"- {b}" for b in bullets) +
            f"\n\nJD:\n{(jd_text or '')[:1500]}\n\nCANDIDATE FACTS:\n{(profile_text or '')[:1200]}\n\n"
            "Reply as:\n1. <bullet> / <bullet>\n2. <bullet> / <bullet>")
        out = llm(prompt)
        allowed = _supported_numbers(" ".join(bullets or []) + " " + (profile_text or ""))
        alts = []
        for line in re.split(r"\n(?=\d+[.)])", out if isinstance(out, str) else ""):
            line = re.sub(r"^\s*\d+[.)]\s*", "", line).strip()
            if not line:
                continue
            # Strip any ** the model still inserted — Rewrite output is plain;
            # bolding is only ever applied by the Highlight pass.
            parts = [_natural_bullet(_ground_bullet(p.strip().replace("**", ""), allowed))
                     for p in re.split(r"\s*/\s*|\n", line) if p.strip()]
            if parts:
                alts.append(parts[:3])
            if len(alts) >= n:
                break
        return alts
    except Exception:
        return []
