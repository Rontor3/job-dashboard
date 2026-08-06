"""Orchestrate the LinkedIn hiring-post digest: fetch -> normalize -> rank ->
store. Ranking reuses the profile embedding (match/embedder.cosine). Pure
functions take ``fetched_at`` as input rather than reading the clock.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from job_dashboard.db import upsert_hiring_post
from job_dashboard.match.embedder import cosine

KEYWORDS = [
    "hiring ML engineer",
    "hiring machine learning engineer",
    "hiring data scientist",
    "hiring forward deployed engineer",
    "hiring founding engineer",
    "startup hiring ML engineer",
]


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


def run_digest(conn, fetcher, keywords, profile_text, *,
               embed_model=None, fetched_at, on_progress=None):
    model = embed_model
    profile_vec = model.encode([profile_text])[0] if model else None

    by_url = {}
    for kw in keywords:
        if on_progress:
            on_progress(kw)
        for d in (fetcher.search_posts(kw) or []):
            post = to_hiring_post(d, kw)
            if post is None or post.url in by_url:
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
