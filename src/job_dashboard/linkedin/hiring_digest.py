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
    role_title: str = ""
    company: str = ""
    judged: bool = False      # a model call produced the verdict (so it is worth caching)


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
    if not is_target_role(f"{post.poster_headline} {post.text}"):  # no ML/AI/DS token → skip the ~30s LLM call
        return False, None, ""
    got = {}
    if role_fn is not None:
        try:
            got = role_fn({"text": post.text, "poster_headline": post.poster_headline,
                           "poster_name": post.poster_name}) or {}
        except Exception:  # noqa: BLE001
            got = {}
    post.judged = bool(got)
    title = got.get("title") or ""
    if not (is_target_role(title) if title else is_target_role(post.text[:300])):
        return False, None, ""
    post.role_title, post.company = title, got.get("company") or ""
    fit = got.get("fit")
    if fit is None:
        return True, None, got.get("reason") or ""
    return fit >= MIN_FIT, fit / 100, got.get("reason") or ""


def is_target_post(post, role_fn=None):
    return judge(post, role_fn)[0]


def run_digest(conn, fetcher, keywords, profile_text, *,
               embed_model=None, fetched_at, on_progress=None, on_event=None, role_fn=None):
    """Search each keyword, score the new posts, and store every kept post AS SOON
    AS it is scored (a later failure or expired session loses nothing). A verdict
    already paid for (same post text, same résumé) is reused, not re-asked.
    ``on_event(dict)`` reports progress: stage 'search' / 'score' / 'done'."""
    import hashlib
    from job_dashboard.db_hiring import judged_get, judged_put
    from job_dashboard.linkedin.contacts import text_key
    model = embed_model
    profile_vec = model.encode([profile_text])[0] if model else None
    phash = hashlib.sha1(f"{profile_text}|{MIN_FIT}".encode()).hexdigest()
    emit = on_event or (lambda e: None)
    stats = {"found": 0, "scored": 0, "cached": 0, "kept": 0}

    by_url, seen_text = {}, set()
    for ki, kw in enumerate(keywords):
        if on_progress:
            on_progress(kw)
        emit({"stage": "search", "i": ki + 1, "n": len(keywords), "keyword": kw, **stats})
        try:
            found = fetcher.search_posts(kw) or []
        except LinkedInAuthError:
            # Expired cookies won't recover mid-run — abort so the API can
            # surface the re-paste message (posts already stored stay).
            raise
        except Exception:  # noqa: BLE001
            # A transient per-keyword browser error must not discard the posts
            # already gathered from other keywords — skip this keyword.
            continue
        fresh = []
        for d in found:
            post = to_hiring_post(d, kw)
            tk = post and text_key(post.text)
            if post is None or post.url in by_url or tk in seen_text:
                continue
            seen_text.add(tk)
            fresh.append((post, tk))
        stats["found"] += len(fresh)
        for j, (post, tk) in enumerate(fresh):
            emit({"stage": "score", "i": ki + 1, "n": len(keywords), "keyword": kw,
                  "j": j + 1, "m": len(fresh), **stats})
            hit = judged_get(conn, tk, phash)
            if hit:
                keep, fit, post.fit_reason = bool(hit["keep"]), hit["fit"], hit["reason"] or ""
                post.role_title, post.company = hit["title"] or "", hit["company"] or ""
                stats["cached"] += 1
            else:
                keep, fit, post.fit_reason = judge(post, role_fn)
                if post.judged and (fit is not None or not keep):   # a real verdict, not a model failure
                    judged_put(conn, tk, phash, keep, fit, post.fit_reason, post.role_title, post.company)
            stats["scored"] += 1
            if not keep:
                continue
            if fit is not None:
                post.fit_score = fit          # résumé judge beats embedding cosine
            elif profile_vec is not None:
                post.fit_score = rank_post(post.text, profile_vec, model)
            by_url[post.url] = post
            row = asdict(post)
            row["fetched_at"] = fetched_at
            upsert_hiring_post(conn, row)
            stats["kept"] += 1
    emit({"stage": "done", **stats})
    return sorted(by_url.values(), key=lambda p: -p.fit_score)
