"""Parse a rendered LinkedIn content-search page into post dicts.

Pure BeautifulSoup — no browser, no network. LinkedIn's search results are
server-driven UI with HASHED, per-deploy CSS class names and no post permalinks
or activity URNs in the DOM, so we key off stable hooks instead: each result is
a ``role="listitem"``; the poster's name comes from the ``img[alt^="View "]``
avatar and their link from the ``/in/`` profile anchor; the post body, degree,
and timestamp are recovered from the card's text. Because there is no post URL,
each card links to the hiring PERSON's profile (who you'd contact anyway); a
short body hash is appended as a URL fragment so two different posts by the same
person don't collapse during dedup. Never raises; a card missing name/body is
skipped.
"""
from __future__ import annotations

import hashlib
import re
import urllib.parse

from bs4 import BeautifulSoup

# Relative time token LinkedIn renders on a post ("4h", "13h", "2d", "1w"...).
_TIME = re.compile(r"\b(\d+)\s*(mo|yr|h|d|w|m)\b")

# The actor line ends with a connection-degree / follow control; the post body
# begins after it. Longest/most-specific first.
_ACTOR_SEP = (" • Connect ", " • Following ", " • Follow ", " • Message ",
              " • 3rd+ ", " • 3rd ", " • 2nd ", " • 1st ")


def _poster_name(card) -> str:
    # Avatar alt is either "View {Name}'s profile" or "{Name}'s profile".
    img = (card.select_one('img[alt^="View "]')
           or card.select_one('img[alt*="profile"]'))
    alt = (img.get("alt") if img else "") or ""
    name = alt[len("View "):] if alt.startswith("View ") else alt
    # Alt is "{Name}'s profile" possibly followed by ", hiring" — cut at the
    # "'s profile" marker (any apostrophe variant) and keep the name before it.
    name = re.split(r"[’'`ʼ’]s\s+profile", name)[0]
    return name.strip().rstrip(",").replace(", hiring", "").strip(" ,")


def _apply_link(card) -> str | None:
    """The actual job/apply link embedded in the post, best-first: LinkedIn job
    posting > external link behind LinkedIn's safety redirect > any external
    anchor > lnkd.in/URL in the body text. Tracking query params are stripped."""
    # 1. LinkedIn job posting permalink
    a = card.select_one('a[href*="/jobs/view/"]')
    if a and a.get("href"):
        return a["href"].split("?")[0]
    # 2. external link wrapped in LinkedIn's /safety/go/?url=<encoded>
    for a in card.select('a[href*="/safety/go/"]'):
        m = re.search(r"[?&]url=([^&]+)", a.get("href", ""))
        if m:
            return urllib.parse.unquote(m.group(1))
    # 3. any plain external (non-linkedin) anchor
    for a in card.select("a[href]"):
        h = a.get("href", "")
        if h.startswith("http") and "linkedin.com" not in h:
            return h.split("?")[0]
    # 4. a bare lnkd.in / http URL sitting in the post text
    m = re.search(r"https?://\S+|lnkd\.in/\S+", card.get_text(" ", strip=True))
    if m:
        u = m.group(0).rstrip(".,)")
        return u if u.startswith("http") else "https://" + u
    return None


def _one(card) -> dict | None:
    try:
        text = re.sub(r"\s+", " ", card.get_text(" ", strip=True))
        if len(text) < 60:
            return None
        name = _poster_name(card)
        prof = card.select_one('a[href*="/in/"]')
        profile = prof.get("href").split("?")[0] if prof and prof.get("href") else None
        if not name or not profile:
            return None

        # Body = the text after the actor line's degree/follow control.
        body = text
        for sep in _ACTOR_SEP:
            if sep in text:
                body = text.split(sep, 1)[1].strip()
                break
        if not body or len(body) < 15:
            return None

        # Headline = the actor block between the name and the timestamp.
        actor = text.split(body, 1)[0]
        tm = _TIME.search(actor) or _TIME.search(text)
        headline = actor
        for chunk in ("Feed post", name, f"{name}’s profile", f"{name}'s profile",
                      "3rd+", "1st", "2nd", "3rd", "Connect", "Following",
                      "Follow", "Message", "•", "·"):
            headline = headline.replace(chunk, " ")
        if tm:
            headline = headline.replace(tm.group(0), " ")
        headline = re.sub(r"\s+", " ", headline).strip(" •·|-+,")

        # Prefer the actual job/apply link embedded in the post; else fall back
        # to the hiring person's profile (uniquified by a body hash so two posts
        # by one person don't dedup to one).
        digest = hashlib.sha1(body[:200].encode("utf-8", "replace")).hexdigest()[:10]
        url = _apply_link(card) or f"{profile}#{digest}"
        return {
            "url": url,
            "poster_name": name,
            "poster_headline": headline,
            "text": body,
            "posted_at": tm.group(0) if tm else None,
        }
    except Exception:  # noqa: BLE001 — parsing must never crash the digest
        return None


def parse_posts_html(html: str) -> list[dict]:
    # Whole body guarded so the "never raise" invariant holds even for a
    # pathological tree (e.g. a RecursionError during .select()).
    try:
        soup = BeautifulSoup(html or "", "html.parser")
        out = []
        for card in soup.select("[role=listitem]"):
            post = _one(card)
            if post is not None:
                out.append(post)
        return out
    except Exception:  # noqa: BLE001
        return []
