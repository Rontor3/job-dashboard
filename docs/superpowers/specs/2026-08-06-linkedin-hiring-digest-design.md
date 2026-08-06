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

LinkedIn exposes no official API for feed posts. We use the **unofficial
Voyager API** (the same internal API the LinkedIn web app calls), authenticated
with the candidate's own browser session cookies:

- `LINKEDIN_LI_AT` — the session token (~150–200 chars; **not** `ajax:`-prefixed)
- `LINKEDIN_JSESSIONID` — the CSRF cookie (~25 chars, **`ajax:`-prefixed**)

Both live in `.env` only (already git-ignored). Request construction:
- **Cookie header:** `li_at=<LI_AT>; JSESSIONID="<JSESSIONID>"` (quotes required)
- **csrf-token header:** `<JSESSIONID>` **without** surrounding quotes
  (`env.py` already strips quotes on load)

**Volume is deliberately tiny** — one search per keyword, once per manual
refresh — to stay a well-behaved client. ToS discourages scraping; this is a
personal, low-volume, read-only digest and the caveats are documented in the
runbook.

## Architecture

```
.env cookies ─▶ voyager.py (auth + auto-resolve queryId + content search)
                     │  per keyword, datePosted = past-24h
                     ▼
             hiring_digest.py  ─ parse → normalize → dedup(url) → rank(profile) → store
                     ▼
             hiring_posts table ─▶ /api/hiring/* ─▶ "Hiring Signals" tab
```

### `linkedin/voyager.py` — authenticated client

```python
class LinkedInAuthError(RuntimeError): ...   # cookie missing/expired → clear message

class VoyagerClient:
    def __init__(self, li_at: str, jsessionid: str, *, opener=None): ...
    def me(self) -> dict: ...                          # auth probe (used by tests/health)
    def resolve_search_query_id(self) -> str: ...      # AUTO-resolve current queryId
    def search_posts(self, keyword: str, *, date_posted="past-24h",
                     count=20) -> list[dict]: ...       # raw post objects
```

- **Auto-resolves the current search `queryId` at runtime** (parse it from the
  authenticated search page / bootstrap payload) and caches it for the run. No
  hardcoded id — this self-heals when LinkedIn rotates the id, because the
  candidate cannot fetch it manually each time.
- A 302/401 response (unauthenticated) → raise `LinkedInAuthError(
  "LinkedIn cookie expired — re-paste li_at/JSESSIONID from your browser")`
  rather than returning empty silently.
- A 429 → raise a clear rate-limit error (caller surfaces "try again later").
- **Never logs cookie values.** Injectable `opener` seam so tests never hit
  the network.

### `linkedin/hiring_digest.py` — orchestration

```python
@dataclass
class HiringPost:
    url: str; poster_name: str; poster_headline: str
    text: str; posted_at: str | None; keyword: str
    fit_score: float

def parse_post(raw: dict, keyword: str) -> HiringPost | None   # never raises → None on odd shape
def rank_post(post: HiringPost, profile_vec, model) -> float   # cosine vs profile
def run_digest(conn, client, keywords, profile_text, *,
               embed_model=None, on_progress=None) -> list[HiringPost]
```

- For each keyword: `search_posts` → `parse_post` (drop unparseable) → keep only
  posts inside the **24-hour** window → **dedup by post URL** → rank.
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

- `POST /api/hiring/refresh` → runs `run_digest`, returns `{fetched, new, ranked}`.
  Injectable client (like `resume_engine`) so tests use a fake, never the network.
  Cookie/expiry/rate-limit errors → 503 with the clear message.
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

- Missing/expired cookie → `LinkedInAuthError` → API 503 with re-paste guidance.
- queryId auto-resolve fails → clear error surfaced, no crash.
- Rate-limited (429) → clear "try again later".
- `parse_post` never raises → returns `None`, the post is skipped.
- All LinkedIn network access is read-only and low-volume.

## Testing

Backend (pytest, network-free via injected `opener`/client):
- Header construction: csrf-token equals JSESSIONID sans quotes; Cookie header
  formats both cookies with `li_at=…; JSESSIONID="…"`.
- `resolve_search_query_id` extracts the id from a fixture page; missing id →
  clear error.
- `search_posts`: 302 → `LinkedInAuthError`; 429 → rate-limit error.
- `parse_post`: fixture raw → `HiringPost`; odd/missing fields → `None` (never raises).
- 24-hour window filtering and **dedup by url**.
- `rank_post`: monotonic with cosine (a fake embed model).
- `db.py` CRUD round-trips; `/api/hiring/*` with a fake client (refresh count,
  list ordering by fit_score, dismiss).
- Live e2e: `skipif not os.getenv("LINKEDIN_LI_AT")` — real search returns ≥0
  parseable posts.

Frontend (Vitest):
- Tab renders; Refresh posts to `/api/hiring/refresh` then lists posts.
- Post card shows poster/blurb/fit/link; dismiss removes it.
- Auth-error state renders the re-paste message.

## Global constraints

- Python 3.11, pytest; React/Vite/Vitest; files under 500 lines.
- **Cookies live in `.env` only** — never logged, never committed, never sent
  anywhere except LinkedIn itself.
- **Read-only, low-volume, no login automation, no writes to LinkedIn.**
- **queryId is auto-resolved at runtime** — never hardcoded.
- Engine takes `fetched_at`/timestamps as inputs (no hidden clock calls in
  pure functions), mirroring the existing codebase seams.
- Reuse existing seams: `match/embedder.py`, `match/profile_text.py`, `env.py`,
  the ui-v2 tab shell, the injected-engine API pattern.
```
