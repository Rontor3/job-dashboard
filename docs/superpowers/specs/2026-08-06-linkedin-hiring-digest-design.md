# LinkedIn Hiring Digest — Design

**Date:** 2026-08-06
**Status:** Approved (design via brainstorming), pending spec review
**Branch:** `linkedin-hiring-digest` (off `resume-block-editor` tip, which carries the ui-v2 tab system)
**Depends on:** `match/embedder.py`, `match/profile_text.py`, the ui-v2 tab shell, `env.py`

## Goal

A **daily digest of individual LinkedIn "who's hiring" posts** — the informal
"my team is hiring for X" signal a person writes, not official job listings —
for the candidate's target roles, surfaced in a **separate "Hiring Signals"
tab**, ranked against the candidate's profile, and limited to the **last 24
hours** so nothing stale (the 4-week-old, now-closed listings problem) appears.

Feasibility already proven live: the candidate's `li_at` / `JSESSIONID` cookies
authenticate to LinkedIn's Voyager API (`GET /voyager/api/me` → 200).

## Non-goals

- **Not** official LinkedIn Jobs listings — that overlaps the existing Browse
  feed. This tab is *only* individual hiring posts.
- **No writes to LinkedIn** — read-only. No auto-connect, no messaging, no apply.
- **No credential handling** — the candidate supplies their own session cookies
  in `.env`; we never see or store a password, never automate login.
- No new ranking engine — reuse the profile embedding + cosine.

## Data source & the cookie model

LinkedIn exposes no official API for feed posts. We originally tried the
unofficial **Voyager JSON API** with the candidate's session cookies, and it
authenticated (`/voyager/api/me` → 200) — but LinkedIn fronts scripted HTTP
with a **Cloudflare JavaScript bot-challenge** (`__cf_bm`): raw `urllib`/
`requests` clients get 302-looped on both the HTML search pages *and* the search
JSON endpoints, and repeated attempts soft-flag the session. A headless-plain-
HTTP client is therefore **not viable** for search. (Auth-layer proof and the
302 findings are recorded in the plan's ledger.)

Instead we drive a **real Chrome browser via Selenium**, which executes the JS
challenge like any human browser and sails past the bot wall. The candidate's
own browser session cookies authenticate it:

- `LINKEDIN_LI_AT` — the session token (~150–200 chars; **not** `ajax:`-prefixed)
- `LINKEDIN_JSESSIONID` — the CSRF cookie (~25 chars, **`ajax:`-prefixed**)

Both live in `.env` only (already git-ignored). The fetcher opens Chrome, visits
`linkedin.com`, injects the two cookies, and reloads to land logged-in — **no
password, no login automation** (the cookies do the auth).

**Human-mimicry / low-volume discipline** (from the reference approach): one
search per keyword per manual refresh, **randomized delays** (2–5 s) between
actions, a few gentle scrolls to load posts, a hard **rate cap** (~2–3 posts/min
of activity), and **never run unattended 24/7**. ToS discourages scraping; this
is a personal, read-only, low-volume digest and the caveats live in the runbook.

## Architecture

```
.env cookies ─▶ browser_fetch.py  (real Chrome via Selenium: inject cookies →
                     │             navigate search → scroll w/ random delays →
                     │             page_source) ── per keyword, "past-24h"
                     ▼
              post_parse.py  (BeautifulSoup: rendered DOM → post dicts)
                     ▼
             hiring_digest.py  ─ dict → HiringPost → dedup(url) → rank(profile) → store
                     ▼
             hiring_posts table ─▶ /api/hiring/* ─▶ "Hiring Signals" tab
```

### `linkedin/post_parse.py` — rendered-HTML parser (pure, testable)

```python
def parse_posts_html(html: str) -> list[dict]:
    """BeautifulSoup over a rendered search-results page → list of post dicts
    {url, poster_name, poster_headline, text, posted_at}. Never raises; skips
    cards missing url/text. Selectors target the feed post cards
    (e.g. div[data-view-name='feed-full-update']) with defensive fallbacks."""
```

Pure function → unit-tested with a fixture HTML snippet, no browser needed. This
is where LinkedIn markup changes are absorbed.

### `linkedin/browser_fetch.py` — Selenium fetcher

```python
class LinkedInAuthError(RuntimeError): ...  # cookies missing/expired / logged out

class LinkedInBrowserFetcher:
    def __init__(self, li_at: str, jsessionid: str, *, driver_factory=None,
                 headless: bool = False, max_scrolls: int = 3, sleep=None): ...
    def search_posts(self, keyword: str, *, date_posted="past-24h") -> list[dict]:
        """Open Chrome, inject cookies, load the content-search URL for keyword,
        scroll with randomized delays, return parse_posts_html(page_source)."""
```

- Launches a real Chrome (Selenium 4 auto-manages the driver). `driver_factory`
  is injectable so tests pass a **fake driver** returning canned `page_source`
  — no real browser in unit tests.
- Injects the two cookies (visit `linkedin.com`, `add_cookie`, reload). If the
  page lands on a login/authwall → raise `LinkedInAuthError("LinkedIn session
  expired — re-paste li_at/JSESSIONID from your browser")`.
- Randomized `sleep` (default `time.sleep(random 2–5 s)`, injectable to a no-op
  in tests) between navigation and scrolls; closes the driver in a `finally`.
- **Never logs cookie values.**

### `linkedin/hiring_digest.py` — orchestration

```python
@dataclass
class HiringPost:
    url: str; poster_name: str; poster_headline: str
    text: str; posted_at: str | None; keyword: str
    fit_score: float

def to_hiring_post(d: dict, keyword: str) -> HiringPost | None  # never raises → None on odd shape
def rank_post(text: str, profile_vec, model) -> float          # cosine vs profile
def run_digest(conn, fetcher, keywords, profile_text, *,
               embed_model=None, fetched_at, on_progress=None) -> list[HiringPost]
```

- For each keyword: `fetcher.search_posts(kw)` → `to_hiring_post` (drop dicts
  missing url/text) → **dedup by post URL** → rank → store. The 24-hour freshness
  is enforced at fetch time (the `past-24h` search filter) and on read
  (`hiring_posts(within_hours=24)`).
- **Ranking reuses `match/embedder.py`** (`load_default_model`, `cosine`) and
  `match/profile_text.py`: embed each post's text, cosine vs the profile vector,
  store as `fit_score`. Pure-embedding for v1 (fast, no per-post LLM); an LLM
  "why it fits" line is a later enhancement.
- Upsert into `hiring_posts` (dedup on `url`); returns the ranked list.

### Keywords (config, candidate-editable)

Stored as a simple constant list in `linkedin/hiring_digest.py` (v1):

```
"hiring ML engineer"
"hiring machine learning engineer"
"hiring data scientist"
"hiring forward deployed engineer"
"hiring founding engineer"
"startup hiring ML engineer"
```

### Database — `hiring_posts`

| column | notes |
|--------|-------|
| `id` | PK |
| `url` | **UNIQUE** — dedup key |
| `poster_name`, `poster_headline` | text |
| `text` | the hiring blurb |
| `posted_at` | ISO date/relative, best-effort from the post |
| `keyword` | which search surfaced it |
| `fit_score` | REAL, cosine vs profile |
| `fetched_at` | ISO timestamp (passed in, not `Date.now()` in engine) |
| `dismissed` | INTEGER default 0 — candidate can hide a post |

CRUD in `db.py`: `upsert_hiring_post`, `hiring_posts(conn, within_hours=24)`,
`dismiss_hiring_post`.

### API — `api/hiring_routes.py` (its own router, <500 lines)

- `POST /api/hiring/refresh` → runs `run_digest`, returns `{ranked, fetched}`.
  Injectable `hiring_fetcher` (like `resume_engine`) so tests use a fake, never a
  real browser. `LinkedInAuthError` → 503 with the re-paste message.
- `GET /api/hiring/posts?within_hours=24` → ranked list for the tab.
- `POST /api/hiring/posts/{id}/dismiss` → hide a post.

### Frontend — new "Hiring Signals" tab

- A third tab alongside Browse / Tracker (reuse the ui-v2 tab shell).
- **Refresh** button → `POST /api/hiring/refresh` (shows "Searching LinkedIn…"),
  then loads `GET /api/hiring/posts`.
- Post cards: poster name + headline, the hiring blurb, a **fit badge**, "posted
  Xh ago", and an outbound link to the LinkedIn post. Dismiss (×) per card.
- Empty/expired states: friendly copy — "No hiring posts in the last 24h" and,
  on auth error, "LinkedIn session expired — re-paste your cookies in `.env`".

## Cadence

- **v1: manual Refresh button** — the candidate clicks it (full control, no
  surprise traffic).
- Later (out of scope): an optional daily background run reusing the existing
  background-refresh infrastructure.

## Error handling

- Missing/expired cookie (login/authwall) → `LinkedInAuthError` → API 503 with
  re-paste guidance.
- `parse_posts_html` / `to_hiring_post` never raise → a bad card is skipped.
- Selenium/driver failure (Chrome not installed, driver error) → surfaced as a
  clear 503 ("couldn't launch the browser"), never a silent empty result.
- The browser driver is always closed in a `finally`.
- All LinkedIn access is read-only, human-paced, and low-volume.

## Testing

Backend (pytest, **no real browser** via injected `driver_factory` / fetcher):
- `parse_posts_html`: a fixture rendered-HTML snippet → the expected post dicts;
  a card missing url/text is skipped; garbage html → `[]` (never raises).
- `LinkedInBrowserFetcher.search_posts` with a **fake driver** (canned
  `page_source`, records `get`/`add_cookie` calls, injectable no-op `sleep`):
  returns parsed dicts; a login-page `page_source` → `LinkedInAuthError`.
- `to_hiring_post`: dict → `HiringPost`; missing fields → `None` (never raises).
- **dedup by url**; `rank_post` monotonic with cosine (a fake embed model);
  `run_digest` with a fake fetcher stores + dedups.
- `db.py` CRUD round-trips; `/api/hiring/*` with a fake fetcher (refresh count,
  list ordering by fit_score, dismiss, auth error → 503).
- Live e2e: `skipif not os.getenv("LINKEDIN_LI_AT")` — a real single-keyword
  search returns a list (≥0) without raising. Run sparingly.

Frontend (Vitest):
- Tab renders; Refresh posts to `/api/hiring/refresh` then lists posts.
- Post card shows poster/blurb/fit/link; dismiss removes it.
- Auth-error state renders the re-paste message.

## Global constraints

- Python 3.11, pytest; React/Vite/Vitest; files under 500 lines.
- New deps: `selenium`, `beautifulsoup4` (added to `requirements.txt`); Chrome
  must be installed (Selenium 4 auto-manages the driver).
- **Cookies live in `.env` only** — never logged, never committed, never sent
  anywhere except LinkedIn itself.
- **Read-only, human-paced, low-volume, no login automation, no writes.**
- Selenium is fully behind an **injectable `driver_factory`** so the whole suite
  runs with no browser and no network; live paths are `skipif`-guarded.
- Engine takes `fetched_at`/timestamps as inputs (no hidden clock calls in
  pure functions), mirroring the existing codebase seams.
- Reuse existing seams: `match/embedder.py`, `match/profile_text.py`, `env.py`,
  the ui-v2 tab shell, the injected-engine API pattern.
```
