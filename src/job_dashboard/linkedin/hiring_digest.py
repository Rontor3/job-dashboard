"""Orchestrate the LinkedIn hiring-post digest: fetch -> normalize -> rank ->
store. Ranking reuses the profile embedding (match/embedder.cosine). Pure
functions take ``fetched_at`` as input rather than reading the clock.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from job_dashboard.db import upsert_hiring_post
from job_dashboard.linkedin.browser_fetch import LinkedInAuthError
from job_dashboard.match.embedder import cosine

# Specific role titles only (core of source_registry.SEARCH_TERMS). Generic
# searches like "hiring founding engineer" pulled civil/electrical/mechanical
# posts. Each keyword is one LinkedIn search per Refresh, so keep this short.
HIRING_ROLES = [
    "machine learning engineer",
    "AI engineer",
    "data scientist",
    "LLM engineer",
    "generative AI engineer",
    "applied scientist",
    "MLOps engineer",
    "forward deployed engineer",
]
KEYWORDS = [f"hiring {r}" for r in HIRING_ROLES]


@dataclass
class HiringPost:
    url: str
    poster_name: str
    poster_headline: str
    text: str
    posted_at: str | None
    keyword: str
    fit_score: float = 0.0


def to_hiring_post(d, keyword):
    """Normalize a fetched post dict into a HiringPost. Never raises."""
    try:
        url, text, name = d.get("url"), d.get("text"), d.get("poster_name")
        if not url or not text or not name:
            return None
        return HiringPost(
            url=str(url), poster_name=str(name),
            poster_headline=str(d.get("poster_headline") or ""),
            text=str(text), posted_at=d.get("posted_at"), keyword=keyword,
        )
    except Exception:  # noqa: BLE001
        return None


def rank_post(text, profile_vec, model):
    try:
        return float(cosine(profile_vec, model.encode([text])[0]))
    except Exception:  # noqa: BLE001
        return 0.0


def is_target_post(post, role_fn=None):
    """Keep a post only if the role it hires for is in the ML/AI/DS family
    (``match.relevance.is_target_role``). Title comes from ``role_fn`` (local
    Ollama); a post naming no clear role is judged by its opening lines."""
    from job_dashboard.match.relevance import is_target_role
    title = ""
    if role_fn is not None:
        try:
            title = role_fn({"text": post.text, "poster_headline": post.poster_headline}).get("title") or ""
        except Exception:  # noqa: BLE001
            title = ""
    return is_target_role(title) if title else is_target_role(post.text[:300])


def run_digest(conn, fetcher, keywords, profile_text, *,
               embed_model=None, fetched_at, on_progress=None, role_fn=None):
    model = embed_model
    profile_vec = model.encode([profile_text])[0] if model else None

    by_url = {}
    for kw in keywords:
        if on_progress:
            on_progress(kw)
        try:
            found = fetcher.search_posts(kw) or []
        except LinkedInAuthError:
            # Expired cookies won't recover mid-run — abort so the API can
            # surface the re-paste message.
            raise
        except Exception:  # noqa: BLE001
            # A transient per-keyword browser error must not discard the posts
            # already gathered from other keywords — skip this keyword.
            continue
        for d in found:
            post = to_hiring_post(d, kw)
            if post is None or post.url in by_url or not is_target_post(post, role_fn):
                continue
            if profile_vec is not None:
                post.fit_score = rank_post(post.text, profile_vec, model)
            by_url[post.url] = post

    ranked = sorted(by_url.values(), key=lambda p: -p.fit_score)
    for post in ranked:
        row = asdict(post)
        row["fetched_at"] = fetched_at
        upsert_hiring_post(conn, row)
    return ranked
