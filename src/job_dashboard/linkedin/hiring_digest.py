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
    fit_reason: str = ""


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


# Posts the résumé judge scores below this are dropped (0-100 scale).
MIN_FIT = 50


def judge(post, role_fn=None):
    """(keep, fit_0_1_or_None, reason). Keeps a post only if its role title is in
    the ML/AI/DS family (``is_target_role``) and, when ``role_fn`` scores it
    against the résumé, the fit is >= MIN_FIT. No title -> judge the opening."""
    from job_dashboard.match.relevance import is_target_role
    got = {}
    if role_fn is not None:
        try:
            got = role_fn({"text": post.text, "poster_headline": post.poster_headline,
                           "poster_name": post.poster_name}) or {}
        except Exception:  # noqa: BLE001
            got = {}
    title = got.get("title") or ""
    if not (is_target_role(title) if title else is_target_role(post.text[:300])):
        return False, None, ""
    fit = got.get("fit")
    if fit is None:
        return True, None, got.get("reason") or ""
    return fit >= MIN_FIT, fit / 100, got.get("reason") or ""


def is_target_post(post, role_fn=None):
    return judge(post, role_fn)[0]


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
            if post is None or post.url in by_url:
                continue
            keep, fit, post.fit_reason = judge(post, role_fn)
            if not keep:
                continue
            if fit is not None:
                post.fit_score = fit          # résumé judge beats embedding cosine
            elif profile_vec is not None:
                post.fit_score = rank_post(post.text, profile_vec, model)
            by_url[post.url] = post

    ranked = sorted(by_url.values(), key=lambda p: -p.fit_score)
    for post in ranked:
        row = asdict(post)
        row["fetched_at"] = fetched_at
        upsert_hiring_post(conn, row)
    return ranked
