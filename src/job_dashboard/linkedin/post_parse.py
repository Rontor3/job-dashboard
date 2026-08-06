"""Parse a rendered LinkedIn content-search page into post dicts.

Pure BeautifulSoup — no browser, no network. This is where LinkedIn markup
changes are absorbed (Task 3's live step verifies the selectors against real
rendered HTML). Never raises; a card missing url or text is skipped.
"""
from __future__ import annotations

import urllib.parse

from bs4 import BeautifulSoup

_CARD_SELECTOR = "div[data-view-name='feed-full-update'], div.feed-shared-update-v2"


def _text(node):
    return node.get_text(" ", strip=True) if node else ""


def _post_url(card):
    urn = card.get("data-urn") or ""
    if "activity" in urn:
        # canonical permalink form
        return f"https://www.linkedin.com/feed/update/{urn}/"
    a = card.select_one("a[href*='/feed/update/'], a[href*='/posts/']")
    href = a.get("href") if a and a.get("href") else None
    # A relative href (/feed/update/...) would otherwise resolve against the
    # dashboard origin in the "View on LinkedIn" link — make it absolute.
    return urllib.parse.urljoin("https://www.linkedin.com", href) if href else None


def _one(card) -> dict | None:
    try:
        text = _text(card.select_one(
            ".update-components-text, .feed-shared-inline-show-more-text, "
            ".update-components-update-v2__commentary"))
        name = _text(card.select_one(
            ".update-components-actor__title, .update-components-actor__name"))
        url = _post_url(card)
        if not text or not name or not url:
            return None
        return {
            "url": url,
            "poster_name": name,
            "poster_headline": _text(card.select_one(
                ".update-components-actor__description")),
            "text": text,
            "posted_at": _text(card.select_one(
                ".update-components-actor__sub-description")) or None,
        }
    except Exception:  # noqa: BLE001 — parsing must never crash the digest
        return None


def parse_posts_html(html: str) -> list[dict]:
    # Whole body guarded so the "never raise" invariant holds even for a
    # pathological tree (e.g. a RecursionError during .select()).
    try:
        soup = BeautifulSoup(html or "", "html.parser")
        out = []
        for card in soup.select(_CARD_SELECTOR):
            post = _one(card)
            if post is not None:
                out.append(post)
        return out
    except Exception:  # noqa: BLE001
        return []
