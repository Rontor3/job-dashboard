"""TinyFish-backed company research: search + fetch -> cited impact facts.

``company_research`` builds 2-3 role-relevant "impact" queries (product,
revenue/funding/milestone, and a JD-derived role keyword), searches TinyFish
for each, fetches the top result pages, and extracts sentences that carry a
concrete impact signal (a $/% figure, or a funding/product/launch/customer
cue). Every extracted :class:`Fact` carries the URL it came from.

``search``/``fetch`` are injected (``search(query, api_key=None) ->
list[dict]``, ``fetch(urls, api_key=None) -> list[dict]``); tests supply
fakes. The defaults call the real TinyFish Search/Fetch APIs over HTTP,
lazily importing ``requests`` so this module has no hard dependency on it
until a real call is made.

ANY failure anywhere in the pipeline -- a raising ``search``/``fetch``, an
HTTP error, malformed JSON, no results, no facts -- is caught and this
returns an empty :class:`ResearchBundle` (``facts=[]``, ``empty=True``).
This function NEVER raises.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable

DEFAULT_SEARCH_HOST = "https://api.search.tinyfish.ai"
DEFAULT_FETCH_HOST = "https://api.fetch.tinyfish.ai"

# Bound on how many result URLs we'll fetch across all queries.
_MAX_URLS = 5

# Bound on how many impact facts we'll return, total.
_MAX_FACTS = 8

SearchFn = Callable[..., list[dict]]
FetchFn = Callable[..., list[dict]]


@dataclass
class Fact:
    """One cited, impact-bearing sentence pulled from a fetched page."""

    text: str
    source_url: str


@dataclass
class ResearchBundle:
    """Result of a :func:`company_research` call."""

    facts: list[Fact]
    queries_used: list[str]
    empty: bool


# --------------------------------------------------------------------------
# Query building
# --------------------------------------------------------------------------

_ROLE_KEYWORD_STOPWORDS = {
    "the", "and", "for", "with", "you", "our", "are", "will", "have", "has",
    "this", "that", "your", "role", "job", "team", "work", "years", "year",
    "experience", "strong", "ability", "skills", "using", "who", "what",
    "all", "any", "can", "must", "we", "to", "of", "in", "on", "a", "an",
    "is", "as", "or", "at", "be", "by", "it", "from", "responsible",
}
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+\-.#]{2,}")


def _first_salient_role_keyword(jd_text: str, role: str) -> str:
    """First non-stopword token from ``jd_text`` (falling back to ``role``).

    Deliberately crude -- plain regex tokenization + a small stopword list,
    no NLP -- good enough to seed a role-relevant search query.
    """
    for source in (jd_text, role):
        if not source:
            continue
        for match in _TOKEN_RE.findall(source):
            word = match.lower()
            if word in _ROLE_KEYWORD_STOPWORDS:
                continue
            return word
    return "team"


def _build_queries(company: str, role: str, jd_text: str) -> list[str]:
    keyword = _first_salient_role_keyword(jd_text, role)
    return [
        f"{company} product",
        f"{company} revenue funding milestone",
        f"{company} {keyword}",
    ]


# --------------------------------------------------------------------------
# Impact-sentence extraction
# --------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_WHITESPACE_RE = re.compile(r"\s+")
_NUMERIC_CUE_RE = re.compile(r"[$%]")
_KEYWORD_CUE_RE = re.compile(
    r"\b(funding|round|revenue|product|launch|customers?)\b", re.IGNORECASE
)


def _split_sentences(content: str) -> list[str]:
    normalized = _WHITESPACE_RE.sub(" ", content).strip()
    if not normalized:
        return []
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(normalized) if s.strip()]


def _is_impact_sentence(sentence: str) -> bool:
    return bool(_NUMERIC_CUE_RE.search(sentence) or _KEYWORD_CUE_RE.search(sentence))


def _extract_facts(fetched: list[dict]) -> list[Fact]:
    facts: list[Fact] = []
    seen: set[str] = set()
    for item in fetched:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        content = item.get("content") or ""
        if not url or not content:
            continue
        for sentence in _split_sentences(content):
            if len(facts) >= _MAX_FACTS:
                return facts
            if not _is_impact_sentence(sentence):
                continue
            key = sentence.lower()
            if key in seen:
                continue
            seen.add(key)
            facts.append(Fact(text=sentence, source_url=url))
    return facts


# --------------------------------------------------------------------------
# Default TinyFish HTTP adapters (lazy requests import)
# --------------------------------------------------------------------------


def _extract_results(data) -> list[dict]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        results = data.get("results", data.get("data", []))
        if isinstance(results, list):
            return [r for r in results if isinstance(r, dict)]
    return []


def _default_search(query: str, api_key: str | None = None) -> list[dict]:
    import requests  # lazy import: only needed for a real TinyFish call

    host = os.getenv("TINYFISH_HOST", DEFAULT_SEARCH_HOST)
    key = api_key or os.getenv("TINYFISH_API_KEY")
    resp = requests.get(
        host,
        params={"query": query},
        headers={"X-API-Key": key or ""},
        timeout=15,
    )
    resp.raise_for_status()
    return _extract_results(resp.json())


def _default_fetch(urls: list[str], api_key: str | None = None) -> list[dict]:
    import requests  # lazy import: only needed for a real TinyFish call

    host = os.getenv("TINYFISH_HOST", DEFAULT_FETCH_HOST)
    key = api_key or os.getenv("TINYFISH_API_KEY")
    resp = requests.post(
        host,
        json={"urls": urls},
        headers={"X-API-Key": key or ""},
        timeout=30,
    )
    resp.raise_for_status()
    return _extract_results(resp.json())


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def company_research(
    company: str,
    role: str,
    jd_text: str,
    search: SearchFn | None = None,
    fetch: FetchFn | None = None,
    api_key: str | None = None,
) -> ResearchBundle:
    """Search + fetch TinyFish for cited, impact-bearing facts about ``company``.

    Builds 2-3 role-relevant impact queries, searches each (capping at
    ``_MAX_URLS`` total result URLs), fetches those URLs, and extracts up to
    ``_MAX_FACTS`` deduped impact sentences -- each carrying the URL it came
    from. Any error anywhere (raising ``search``/``fetch``, HTTP failure,
    malformed data, no results, no facts) yields an empty bundle; this
    function never raises.
    """
    queries: list[str] = []
    search_fn = search or _default_search
    fetch_fn = fetch or _default_fetch

    try:
        queries = _build_queries(company, role, jd_text)
        urls: list[str] = []
        seen_urls: set[str] = set()
        for query in queries:
            results = search_fn(query, api_key=api_key) or []
            for result in results:
                url = result.get("url") if isinstance(result, dict) else None
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                urls.append(url)
                if len(urls) >= _MAX_URLS:
                    break
            if len(urls) >= _MAX_URLS:
                break

        if not urls:
            return ResearchBundle([], queries, empty=True)

        fetched = fetch_fn(urls, api_key=api_key) or []
        facts = _extract_facts(fetched)
        return ResearchBundle(facts, queries, empty=not facts)
    except Exception:
        # Any HTTP error, unreachable host, malformed response, etc. ->
        # empty bundle. Never raise.
        return ResearchBundle([], queries, empty=True)
