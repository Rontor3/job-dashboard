# LinkedIn Hiring Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily digest of individual LinkedIn "who's hiring" posts for the candidate's target roles, in a separate "Hiring Signals" tab, limited to the last 24 hours and ranked against the candidate's profile.

**Architecture:** A cookie-authenticated Voyager client (`linkedin/voyager.py`) auto-resolves LinkedIn's rotating search `queryId` at runtime and runs a content search per keyword with the past-24h filter. An orchestrator (`linkedin/hiring_digest.py`) parses, dedups, ranks (reusing `match/embedder.py`), and stores posts in a new `hiring_posts` table. A `/api/hiring/*` router (injectable client, like `resume_engine`) serves a new React "Hiring Signals" tab.

**Tech Stack:** Python 3.11, FastAPI, sqlite3, pytest; urllib (stdlib) for HTTP; sentence-transformers (existing); React + Vite + Vitest.

## Global Constraints

- Python 3.11, pytest; React/Vite/Vitest; every file under 500 lines.
- Cookies (`LINKEDIN_LI_AT`, `LINKEDIN_JSESSIONID`) live in `.env` only — never logged, never committed, never sent anywhere except `www.linkedin.com`.
- **Read-only, low-volume, no login automation, no writes to LinkedIn.**
- **queryId is auto-resolved at runtime — never hardcoded.**
- Cookie header: `li_at=<LI_AT>; JSESSIONID="<JSESSIONID>"` (quotes). csrf-token header: `<JSESSIONID>` **without** surrounding quotes (`env.py` strips them on load).
- Pure functions take timestamps as inputs (`fetched_at`) — no hidden clock calls in engine logic.
- All network access goes through an injectable `opener`/client seam so tests never hit the network. Live tests are guarded `skipif not os.getenv("LINKEDIN_LI_AT")`.
- Reuse existing seams: `match/embedder.py` (`load_default_model`, `cosine`), `match/profile_text.py` (`compose_profile_text`), `env.py`, the ui-v2 `activeTab` tab shell, the `build_*_router(db_path, engine=None)` injected-engine API pattern.

---

### Task 1: `hiring_posts` table + CRUD

**Files:**
- Modify: `src/job_dashboard/db.py` (add `_ensure_hiring_posts_table`, call it in `init_db`, add CRUD)
- Test: `tests/test_hiring_db.py`

**Interfaces:**
- Consumes: `init_db(path)` (existing), `datetime`/`timezone` (already imported in db.py).
- Produces:
  - `upsert_hiring_post(conn, post: dict) -> None` — `post` has keys `url, poster_name, poster_headline, text, posted_at, keyword, fit_score, fetched_at`; dedup on `url` (ON CONFLICT updates fit_score/fetched_at/text, preserves `dismissed`).
  - `hiring_posts(conn, within_hours: int = 24) -> list[dict]` — non-dismissed rows whose `fetched_at` is within `within_hours`, ordered `fit_score DESC`.
  - `dismiss_hiring_post(conn, post_id: int) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hiring_db.py
from datetime import datetime, timezone, timedelta
from job_dashboard.db import (
    init_db, upsert_hiring_post, hiring_posts, dismiss_hiring_post,
)


def _post(url, fit, fetched_at, **kw):
    base = dict(url=url, poster_name="Jane Doe", poster_headline="Hiring Manager",
               text="We are hiring an ML Engineer!", posted_at="2026-08-06",
               keyword="hiring ML engineer", fit_score=fit, fetched_at=fetched_at)
    base.update(kw)
    return base


def test_upsert_dedups_on_url(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc).isoformat()
    upsert_hiring_post(conn, _post("https://li/posts/1", 0.5, now))
    upsert_hiring_post(conn, _post("https://li/posts/1", 0.9, now))  # same url
    rows = hiring_posts(conn, within_hours=24)
    assert len(rows) == 1 and rows[0]["fit_score"] == 0.9


def test_list_orders_by_fit_and_filters_window(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    upsert_hiring_post(conn, _post("u1", 0.3, now.isoformat()))
    upsert_hiring_post(conn, _post("u2", 0.8, now.isoformat()))
    old = (now - timedelta(hours=48)).isoformat()
    upsert_hiring_post(conn, _post("u3", 0.99, old))  # outside 24h window
    rows = hiring_posts(conn, within_hours=24)
    assert [r["url"] for r in rows] == ["u2", "u1"]  # u3 filtered out, sorted by fit


def test_dismiss_hides_post(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc).isoformat()
    upsert_hiring_post(conn, _post("u1", 0.5, now))
    pid = hiring_posts(conn, within_hours=24)[0]["id"]
    dismiss_hiring_post(conn, pid)
    assert hiring_posts(conn, within_hours=24) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_hiring_db.py -v`
Expected: FAIL with ImportError (functions not defined).

- [ ] **Step 3: Add the table + CRUD to `db.py`**

In `init_db`, next to `_ensure_company_classifications_table(conn)`, add `_ensure_hiring_posts_table(conn)`. Then add:

```python
def _ensure_hiring_posts_table(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS hiring_posts (
               id               INTEGER PRIMARY KEY AUTOINCREMENT,
               url              TEXT UNIQUE NOT NULL,
               poster_name      TEXT,
               poster_headline  TEXT,
               text             TEXT,
               posted_at        TEXT,
               keyword          TEXT,
               fit_score        REAL NOT NULL DEFAULT 0,
               fetched_at       TEXT NOT NULL,
               dismissed        INTEGER NOT NULL DEFAULT 0
           )"""
    )


_HIRING_COLS = ("id", "url", "poster_name", "poster_headline", "text",
                "posted_at", "keyword", "fit_score", "fetched_at", "dismissed")


def upsert_hiring_post(conn, post):
    conn.execute(
        """INSERT INTO hiring_posts
               (url, poster_name, poster_headline, text, posted_at,
                keyword, fit_score, fetched_at)
           VALUES (:url, :poster_name, :poster_headline, :text, :posted_at,
                   :keyword, :fit_score, :fetched_at)
           ON CONFLICT(url) DO UPDATE SET
               text=excluded.text, fit_score=excluded.fit_score,
               fetched_at=excluded.fetched_at, keyword=excluded.keyword""",
        post,
    )
    conn.commit()


def hiring_posts(conn, within_hours=24):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=within_hours)).isoformat()
    rows = conn.execute(
        f"""SELECT {', '.join(_HIRING_COLS)} FROM hiring_posts
            WHERE dismissed = 0 AND fetched_at >= ?
            ORDER BY fit_score DESC, id DESC""",
        (cutoff,),
    ).fetchall()
    return [dict(zip(_HIRING_COLS, r)) for r in rows]


def dismiss_hiring_post(conn, post_id):
    conn.execute("UPDATE hiring_posts SET dismissed = 1 WHERE id = ?", (post_id,))
    conn.commit()
```

Ensure `from datetime import datetime, timezone, timedelta` — add `timedelta` if not already imported at the top of `db.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_hiring_db.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Run the full backend suite (no regressions)**

Run: `python3 -m pytest -q`
Expected: all prior tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/job_dashboard/db.py tests/test_hiring_db.py
git commit -m "feat(db): hiring_posts table + CRUD (dedup on url, 24h window)"
```

---

### Task 2: Voyager client core (auth + headers)

**Files:**
- Create: `src/job_dashboard/linkedin/__init__.py` (empty)
- Create: `src/job_dashboard/linkedin/voyager.py`
- Test: `tests/test_voyager_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `class LinkedInAuthError(RuntimeError)`
  - `class LinkedInRateLimit(RuntimeError)`
  - `VoyagerClient(li_at, jsessionid, *, fetch=None)` where `fetch(url, headers) -> (status:int, body:str)`; default uses urllib. Attributes: `.headers` (dict).
  - `VoyagerClient.me() -> dict` (raises `LinkedInAuthError` on 302/401).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_voyager_client.py
import json
import pytest
from job_dashboard.linkedin.voyager import (
    VoyagerClient, LinkedInAuthError,
)


def fake_fetch(responses):
    """responses: list of (status, body); returns a fetch() recording calls."""
    calls = []
    def _fetch(url, headers):
        calls.append((url, headers))
        status, body = responses.pop(0)
        return status, body
    _fetch.calls = calls
    return _fetch


def test_csrf_token_is_jsessionid_without_quotes():
    c = VoyagerClient("LIAT", 'ajax:99', fetch=lambda u, h: (200, "{}"))
    assert c.headers["csrf-token"] == "ajax:99"
    assert 'JSESSIONID="ajax:99"' in c.headers["Cookie"]
    assert "li_at=LIAT" in c.headers["Cookie"]


def test_me_returns_json_on_200():
    body = json.dumps({"included": [{"firstName": "Rakshit", "lastName": "Singh"}]})
    c = VoyagerClient("x", "ajax:1", fetch=fake_fetch([(200, body)]))
    assert c.me()["included"][0]["firstName"] == "Rakshit"


def test_me_raises_auth_error_on_302():
    c = VoyagerClient("x", "ajax:1", fetch=fake_fetch([(302, "")]))
    with pytest.raises(LinkedInAuthError):
        c.me()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_voyager_client.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `linkedin/voyager.py`**

```python
"""Cookie-authenticated LinkedIn Voyager client (read-only).

Uses the candidate's own browser session cookies (li_at, JSESSIONID) from .env
to call LinkedIn's internal Voyager API. No writes, no login automation. Never
logs cookie values. All HTTP goes through an injectable ``fetch`` seam so tests
never touch the network.
"""
from __future__ import annotations

import json
import ssl
import urllib.request

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

try:  # macOS python often lacks a usable default CA bundle
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    _SSL_CTX = ssl.create_default_context()


class LinkedInAuthError(RuntimeError):
    """Cookies missing/expired — the caller should tell the user to re-paste."""


class LinkedInRateLimit(RuntimeError):
    """LinkedIn returned 429 — back off and try later."""


def _urllib_fetch(url, headers):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


class VoyagerClient:
    BASE = "https://www.linkedin.com"

    def __init__(self, li_at, jsessionid, *, fetch=None):
        # env.py strips the surrounding quotes on load, so jsessionid is the
        # bare ``ajax:...`` value here. csrf-token wants it bare; the Cookie
        # header wants it re-quoted.
        csrf = jsessionid.strip().strip('"')
        self._fetch = fetch or _urllib_fetch
        self.headers = {
            "User-Agent": _UA,
            "Accept": "application/vnd.linkedin.normalized+json+2.1",
            "x-restli-protocol-version": "2.0.0",
            "x-li-lang": "en_US",
            "csrf-token": csrf,
            "Cookie": f'li_at={li_at}; JSESSIONID="{csrf}"',
        }

    def _get_json(self, url):
        status, body = self._fetch(url, self.headers)
        if status in (301, 302, 401, 403):
            raise LinkedInAuthError(
                "LinkedIn cookie expired — re-paste li_at/JSESSIONID from your browser"
            )
        if status == 429:
            raise LinkedInRateLimit("LinkedIn rate-limited the request — try again later")
        if status != 200:
            raise RuntimeError(f"LinkedIn returned HTTP {status}")
        try:
            return json.loads(body)
        except ValueError:
            return {}

    def me(self):
        return self._get_json(f"{self.BASE}/voyager/api/me")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_voyager_client.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/linkedin/__init__.py src/job_dashboard/linkedin/voyager.py tests/test_voyager_client.py
git commit -m "feat(linkedin): Voyager client core (cookie auth headers, me(), typed errors)"
```

---

### Task 3: queryId auto-resolve + `search_posts`

**Files:**
- Modify: `src/job_dashboard/linkedin/voyager.py`
- Test: `tests/test_voyager_search.py`

**Interfaces:**
- Consumes: `VoyagerClient`, `LinkedInAuthError`, `LinkedInRateLimit` (Task 2).
- Produces:
  - `VoyagerClient.resolve_search_query_id() -> str` — fetches the authenticated content-search page, regex-extracts the current `voyagerSearchDashClusters.<hash>` id, caches on the instance. Raises `LinkedInAuthError` on redirect, `RuntimeError("could not resolve search queryId")` if none found.
  - `VoyagerClient.search_posts(keyword, *, date_posted="past-24h", count=20) -> list[dict]` — returns the raw included objects from the GraphQL search response (unfiltered; parsing is Task 4).

**⚠ Live-verification required:** this hits an undocumented, versioned endpoint. After the unit tests pass, the implementer MUST run one real search with the candidate's cookie (`.env` present) to confirm the regex + GraphQL variable encoding match live reality, and adjust the extraction (regex, `included` shape) if needed. Keep live requests to ≤3.

- [ ] **Step 1: Write the failing test (network-free, fixtures)**

```python
# tests/test_voyager_search.py
import json
import pytest
from job_dashboard.linkedin.voyager import (
    VoyagerClient, LinkedInAuthError, LinkedInRateLimit,
)


def seq_fetch(responses):
    def _fetch(url, headers):
        return responses.pop(0)
    return _fetch


PAGE_WITH_ID = (
    '<html>...<script>queryId&quot;:&quot;voyagerSearchDashClusters.'
    'abc123def456&quot;...</script></html>'
)


def test_resolve_query_id_extracts_from_page():
    c = VoyagerClient("x", "ajax:1", fetch=seq_fetch([(200, PAGE_WITH_ID)]))
    assert c.resolve_search_query_id() == "voyagerSearchDashClusters.abc123def456"


def test_resolve_query_id_auth_error_on_redirect():
    c = VoyagerClient("x", "ajax:1", fetch=seq_fetch([(302, "")]))
    with pytest.raises(LinkedInAuthError):
        c.resolve_search_query_id()


def test_search_posts_returns_included_objects():
    search_body = json.dumps({"data": {}, "included": [
        {"$type": "com.linkedin.voyager.dash.search.SearchFeedUpdate", "x": 1},
        {"$type": "other", "y": 2},
    ]})
    # first response resolves the queryId, second is the search result
    c = VoyagerClient("x", "ajax:1", fetch=seq_fetch([
        (200, PAGE_WITH_ID), (200, search_body),
    ]))
    out = c.search_posts("hiring ML engineer")
    assert isinstance(out, list) and len(out) == 2


def test_search_posts_rate_limit():
    c = VoyagerClient("x", "ajax:1", fetch=seq_fetch([(200, PAGE_WITH_ID), (429, "")]))
    with pytest.raises(LinkedInRateLimit):
        c.search_posts("hiring ML engineer")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_voyager_search.py -v`
Expected: FAIL (methods not defined).

- [ ] **Step 3: Add the methods to `voyager.py`**

Add `import re` and `import urllib.parse` at the top. Add to `VoyagerClient`:

```python
    _QID_RE = re.compile(r"voyagerSearchDashClusters\.[0-9a-f]{6,}")

    def _get_text(self, url):
        status, body = self._fetch(url, self.headers)
        if status in (301, 302, 401, 403):
            raise LinkedInAuthError(
                "LinkedIn cookie expired — re-paste li_at/JSESSIONID from your browser"
            )
        if status == 429:
            raise LinkedInRateLimit("LinkedIn rate-limited the request — try again later")
        if status != 200:
            raise RuntimeError(f"LinkedIn returned HTTP {status}")
        return body

    def resolve_search_query_id(self):
        if getattr(self, "_query_id", None):
            return self._query_id
        page = self._get_text(
            f"{self.BASE}/search/results/content/"
            "?keywords=hiring&origin=FACETED_SEARCH"
        )
        m = self._QID_RE.search(page)
        if not m:
            raise RuntimeError(
                "could not resolve search queryId — LinkedIn markup changed"
            )
        self._query_id = m.group(0)
        return self._query_id

    def search_posts(self, keyword, *, date_posted="past-24h", count=20):
        query_id = self.resolve_search_query_id()
        kw = urllib.parse.quote(keyword)
        variables = (
            f"(start:0,origin:FACETED_SEARCH,query:(keywords:{kw},"
            "flagshipSearchIntent:SEARCH_SRP,"
            "queryParameters:List("
            "(key:resultType,value:List(CONTENT)),"
            f"(key:datePosted,value:List({date_posted}))"
            "),includeFiltersInResponse:false))"
        )
        url = (f"{self.BASE}/voyager/api/graphql"
               f"?variables={variables}&queryId={query_id}")
        data = self._get_json(url)
        return list(data.get("included") or [])
```

- [ ] **Step 4: Run unit tests to verify they pass**

Run: `python3 -m pytest tests/test_voyager_search.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Live verification (cookie required)**

Run a one-off from the repo root (needs `.env` with valid cookies):

```bash
python3 -c "
import os, sys; sys.path.insert(0,'src')
from job_dashboard.env import load_env_file; load_env_file('.env')
from job_dashboard.linkedin.voyager import VoyagerClient
c = VoyagerClient(os.environ['LINKEDIN_LI_AT'], os.environ['LINKEDIN_JSESSIONID'])
print('queryId:', c.resolve_search_query_id())
posts = c.search_posts('hiring ML engineer')
print('raw included objects:', len(posts))
"
```
Expected: prints a `voyagerSearchDashClusters.<hash>` id and a non-negative count. **If it errors**, inspect the real response shape and adjust the regex / `variables` encoding / `included` handling until it returns objects, keeping to ≤3 live calls. Record what the real post objects look like (their `$type` and where commentary/actor live) in the commit message — Task 4 parsing depends on it.

- [ ] **Step 6: Commit**

```bash
git add src/job_dashboard/linkedin/voyager.py tests/test_voyager_search.py
git commit -m "feat(linkedin): auto-resolve search queryId + content search_posts (live-verified)"
```

---

### Task 4: Digest orchestration (parse, rank, run)

**Files:**
- Create: `src/job_dashboard/linkedin/hiring_digest.py`
- Test: `tests/test_hiring_digest.py`

**Interfaces:**
- Consumes: `upsert_hiring_post` (Task 1); `VoyagerClient.search_posts` (Task 3); `cosine` from `match/embedder.py`.
- Produces:
  - `KEYWORDS: list[str]` (the 6 search phrases).
  - `@dataclass HiringPost` with fields `url, poster_name, poster_headline, text, posted_at, keyword, fit_score`.
  - `parse_post(raw: dict, keyword: str) -> HiringPost | None` — never raises.
  - `rank_post(text: str, profile_vec, model) -> float`.
  - `run_digest(conn, client, keywords, profile_text, *, embed_model=None, fetched_at, on_progress=None) -> list[HiringPost]`.

**Note on `parse_post`:** the exact `raw` shape comes from Task 3's live verification. Implement against the documented shape below; if Task 3's commit recorded a different actual shape, adjust the field lookups and update the fixture in Step 1 to match the real objects. The invariant that MUST hold regardless: `parse_post` never raises and returns `None` when required fields are absent.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hiring_digest.py
from job_dashboard.linkedin.hiring_digest import (
    KEYWORDS, HiringPost, parse_post, rank_post, run_digest,
)
from job_dashboard.db import init_db, hiring_posts


RAW_OK = {
    "actor": {"name": {"text": "Jane Doe"}, "description": {"text": "Eng Manager @ Acme"}},
    "commentary": {"text": {"text": "We're hiring an ML Engineer! DM me."}},
    "socialContent": {"shareUrl": "https://www.linkedin.com/posts/jane_1"},
    "actorNavigationContext": {},
}


class FakeModel:
    """encode([t]) -> [[len-based vec]] so cosine is deterministic in tests."""
    def encode(self, texts):
        return [[float(len(t)), 1.0] for t in texts]


def test_keywords_are_role_specific():
    assert "hiring ML engineer" in KEYWORDS
    assert all("machine learning" != k for k in KEYWORDS)  # no generic noise term


def test_parse_post_ok():
    p = parse_post(RAW_OK, "hiring ML engineer")
    assert isinstance(p, HiringPost)
    assert p.poster_name == "Jane Doe"
    assert "ML Engineer" in p.text
    assert p.url == "https://www.linkedin.com/posts/jane_1"


def test_parse_post_missing_fields_returns_none():
    assert parse_post({}, "k") is None
    assert parse_post({"commentary": {}}, "k") is None  # no url


def test_rank_post_is_cosine():
    model = FakeModel()
    pv = model.encode(["profile text"])[0]
    score = rank_post("some post", pv, model)
    assert 0.0 <= score <= 1.0


def test_run_digest_dedups_and_stores(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))

    class FakeClient:
        def search_posts(self, keyword, **kw):
            # same post surfaced by two keywords -> must dedup on url
            return [RAW_OK]

    posts = run_digest(conn, FakeClient(), ["hiring ML engineer", "hiring data scientist"],
                       "profile text", embed_model=FakeModel(),
                       fetched_at="2026-08-06T00:00:00+00:00")
    stored = hiring_posts(conn, within_hours=24)
    assert len(stored) == 1                       # deduped
    assert stored[0]["poster_name"] == "Jane Doe"
    assert isinstance(posts, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_hiring_digest.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `linkedin/hiring_digest.py`**

```python
"""Orchestrate the LinkedIn hiring-post digest: search -> parse -> rank -> store.

Ranking reuses the profile embedding (match/embedder.cosine). Pure functions
take ``fetched_at`` as input rather than reading the clock, matching the rest of
the codebase.
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


def _dig(d, *path):
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def parse_post(raw, keyword):
    """Map a raw Voyager search object to a HiringPost. Never raises."""
    try:
        url = _dig(raw, "socialContent", "shareUrl") or _dig(raw, "shareUrl")
        text = _dig(raw, "commentary", "text", "text") or _dig(raw, "commentary", "text")
        name = _dig(raw, "actor", "name", "text")
        if not url or not text or not name:
            return None
        return HiringPost(
            url=str(url),
            poster_name=str(name),
            poster_headline=str(_dig(raw, "actor", "description", "text") or ""),
            text=str(text),
            posted_at=_dig(raw, "actor", "subDescription", "text"),
            keyword=keyword,
        )
    except Exception:  # noqa: BLE001 — parsing must never crash the digest
        return None


def rank_post(text, profile_vec, model):
    try:
        vec = model.encode([text])[0]
        return float(cosine(profile_vec, vec))
    except Exception:  # noqa: BLE001
        return 0.0


def run_digest(conn, client, keywords, profile_text, *,
               embed_model=None, fetched_at, on_progress=None):
    """Search each keyword, parse+dedup+rank posts, store them. Returns ranked list."""
    model = embed_model
    profile_vec = model.encode([profile_text])[0] if model else None

    by_url = {}
    for kw in keywords:
        if on_progress:
            on_progress(kw)
        for raw in (client.search_posts(kw) or []):
            post = parse_post(raw, kw)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_hiring_digest.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/linkedin/hiring_digest.py tests/test_hiring_digest.py
git commit -m "feat(linkedin): digest orchestration (parse/rank/dedup/store, KEYWORDS)"
```

---

### Task 5: `/api/hiring/*` router + wiring

**Files:**
- Create: `src/job_dashboard/api/hiring_routes.py`
- Modify: `src/job_dashboard/api/app.py` (build + include the router)
- Test: `tests/test_hiring_api.py`

**Interfaces:**
- Consumes: `run_digest`, `KEYWORDS` (Task 4); `hiring_posts`, `dismiss_hiring_post`, `init_db` (Task 1); `compose_profile_text` (`match/profile_text.py`); `VoyagerClient`, `LinkedInAuthError`, `LinkedInRateLimit` (Tasks 2-3); `load_default_model` (`match/embedder.py`).
- Produces: `build_hiring_router(db_path, hiring_client=None, embed_model=None) -> APIRouter`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hiring_api.py
from fastapi.testclient import TestClient
from job_dashboard.api.app import create_app


RAW_OK = {
    "actor": {"name": {"text": "Jane Doe"}, "description": {"text": "EM @ Acme"}},
    "commentary": {"text": {"text": "Hiring an ML Engineer!"}},
    "socialContent": {"shareUrl": "https://li/posts/jane_1"},
}


class FakeClient:
    def search_posts(self, keyword, **kw):
        return [RAW_OK]


class FakeModel:
    def encode(self, texts):
        return [[float(len(t)), 1.0] for t in texts]


def _client(tmp_path):
    db = str(tmp_path / "t.db")
    app = create_app(db_path=db, hiring_client=FakeClient(), embed_model=FakeModel())
    return TestClient(app)


def test_refresh_then_list(tmp_path):
    client = _client(tmp_path)
    r = client.post("/api/hiring/refresh")
    assert r.status_code == 200 and r.json()["ranked"] >= 1
    posts = client.get("/api/hiring/posts").json()["posts"]
    assert posts[0]["poster_name"] == "Jane Doe"
    assert posts[0]["url"] == "https://li/posts/jane_1"


def test_dismiss(tmp_path):
    client = _client(tmp_path)
    client.post("/api/hiring/refresh")
    pid = client.get("/api/hiring/posts").json()["posts"][0]["id"]
    assert client.post(f"/api/hiring/posts/{pid}/dismiss").status_code == 200
    assert client.get("/api/hiring/posts").json()["posts"] == []


def test_refresh_auth_error_returns_503(tmp_path):
    from job_dashboard.linkedin.voyager import LinkedInAuthError

    class Dead:
        def search_posts(self, keyword, **kw):
            raise LinkedInAuthError("expired")

    db = str(tmp_path / "t.db")
    app = create_app(db_path=db, hiring_client=Dead(), embed_model=FakeModel())
    r = TestClient(app).post("/api/hiring/refresh")
    assert r.status_code == 503 and "re-paste" in r.json()["detail"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_hiring_api.py -v`
Expected: FAIL (`create_app` has no `hiring_client` kwarg / route 404).

- [ ] **Step 3: Write `api/hiring_routes.py`**

```python
"""Hiring-digest API: refresh (search LinkedIn), list, dismiss. Kept in its own
router to respect the 500-line cap; ``create_app`` includes it."""
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from job_dashboard.db import (
    init_db, hiring_posts as db_hiring_posts, dismiss_hiring_post,
)
from job_dashboard.linkedin.hiring_digest import KEYWORDS, run_digest
from job_dashboard.linkedin.voyager import LinkedInAuthError, LinkedInRateLimit
from job_dashboard.match.profile_text import compose_profile_text


def build_hiring_router(db_path, hiring_client=None, embed_model=None) -> APIRouter:
    router = APIRouter()

    @contextmanager
    def db():
        conn = init_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    @router.post("/api/hiring/refresh")
    def refresh():
        if hiring_client is None:
            raise HTTPException(status_code=503,
                                detail="LinkedIn client not configured — set cookies in .env")
        try:
            profile_text = compose_profile_text().text
        except Exception:
            profile_text = ""
        try:
            with db() as conn:
                ranked = run_digest(
                    conn, hiring_client, KEYWORDS, profile_text,
                    embed_model=embed_model,
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                )
        except LinkedInAuthError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except LinkedInRateLimit as e:
            raise HTTPException(status_code=503, detail=str(e))
        return {"ranked": len(ranked), "fetched": len(ranked)}

    @router.get("/api/hiring/posts")
    def list_posts(within_hours: int = 24):
        with db() as conn:
            return {"posts": db_hiring_posts(conn, within_hours=within_hours)}

    @router.post("/api/hiring/posts/{post_id}/dismiss")
    def dismiss(post_id: int):
        with db() as conn:
            dismiss_hiring_post(conn, post_id)
        return {"ok": True}

    return router
```

- [ ] **Step 4: Wire it into `create_app`**

In `src/job_dashboard/api/app.py`: import `build_hiring_router`; add `hiring_client=None, embed_model=None` params to `create_app`; near the other `include_router` calls add:

```python
    app.include_router(build_hiring_router(db_path, hiring_client, embed_model))
```

Then, so the real server gets a live client, in the server entry (`api/serve.py`, where `.env` is loaded) build the default client and pass it to `create_app`:

```python
    import os
    from job_dashboard.linkedin.voyager import VoyagerClient
    from job_dashboard.match.embedder import load_default_model
    li_at, jsess = os.getenv("LINKEDIN_LI_AT"), os.getenv("LINKEDIN_JSESSIONID")
    hiring_client = VoyagerClient(li_at, jsess) if li_at and jsess else None
    # embed_model is lazy/optional; load_default_model() may be heavy — load if available
    try:
        embed_model = load_default_model()
    except Exception:
        embed_model = None
    app = create_app(db_path=..., hiring_client=hiring_client, embed_model=embed_model)
```
(Adapt to the exact existing `serve.py` call — only add the two kwargs; do not change unrelated wiring.)

- [ ] **Step 5: Run tests + full suite**

Run: `python3 -m pytest tests/test_hiring_api.py -v && python3 -m pytest -q`
Expected: new tests PASS; no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/job_dashboard/api/hiring_routes.py src/job_dashboard/api/app.py src/job_dashboard/api/serve.py tests/test_hiring_api.py
git commit -m "feat(api): /api/hiring refresh/list/dismiss (injectable client, auth error -> 503)"
```

---

### Task 6: "Hiring Signals" tab (frontend)

**Files:**
- Create: `frontend/src/components/HiringSignals.jsx`
- Modify: `frontend/src/App.jsx` (third tab), `frontend/src/api.js` (3 calls)
- Test: `frontend/src/__tests__/hiring_signals.test.jsx`

**Interfaces:**
- Consumes: `/api/hiring/refresh`, `/api/hiring/posts`, `/api/hiring/posts/{id}/dismiss` (Task 5).
- Produces: a `HiringSignals` component; `activeTab === "hiring"` branch in App.

- [ ] **Step 1: Add API helpers to `frontend/src/api.js`**

```javascript
export const hiringPosts = () =>
  fetch("/api/hiring/posts").then((r) => r.json());
export const refreshHiring = () =>
  fetch("/api/hiring/refresh", { method: "POST" }).then(async (r) => {
    if (!r.ok) throw new Error((await r.json()).detail || "refresh failed");
    return r.json();
  });
export const dismissHiring = (id) =>
  fetch(`/api/hiring/posts/${id}/dismiss`, { method: "POST" }).then((r) => r.json());
```

- [ ] **Step 2: Write the failing test**

```javascript
// frontend/src/__tests__/hiring_signals.test.jsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import HiringSignals from "../components/HiringSignals.jsx";

const POSTS = {
  posts: [
    { id: 1, url: "https://li/posts/1", poster_name: "Jane Doe",
      poster_headline: "EM @ Acme", text: "Hiring an ML Engineer!",
      posted_at: "5h", keyword: "hiring ML engineer", fit_score: 0.82 },
  ],
};

beforeEach(() => {
  global.fetch = vi.fn((url, opts) => {
    if (String(url).includes("/refresh")) return Promise.resolve({ ok: true, json: () => Promise.resolve({ ranked: 1 }) });
    if (String(url).includes("/dismiss")) return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
    return Promise.resolve({ ok: true, json: () => Promise.resolve(POSTS) });
  });
});

test("lists posts and shows poster + fit", async () => {
  render(<HiringSignals />);
  await waitFor(() => expect(screen.getByText("Jane Doe")).toBeInTheDocument());
  expect(screen.getByText(/Hiring an ML Engineer/)).toBeInTheDocument();
});

test("refresh triggers POST /refresh", async () => {
  render(<HiringSignals />);
  fireEvent.click(screen.getByText(/Refresh/i));
  await waitFor(() =>
    expect(global.fetch.mock.calls.some(([u]) => String(u).includes("/refresh"))).toBe(true)
  );
});

test("dismiss removes the card", async () => {
  render(<HiringSignals />);
  await waitFor(() => expect(screen.getByText("Jane Doe")).toBeInTheDocument());
  fireEvent.click(screen.getByLabelText("Dismiss"));
  await waitFor(() => expect(screen.queryByText("Jane Doe")).toBeNull());
});
```

- [ ] **Step 3: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/__tests__/hiring_signals.test.jsx`
Expected: FAIL (component not found).

- [ ] **Step 4: Write `HiringSignals.jsx`**

```jsx
import React, { useEffect, useState } from "react";
import { hiringPosts, refreshHiring, dismissHiring } from "../api.js";

const BTN = { border: "none", cursor: "pointer", fontSize: 12, padding: "6px 14px",
  borderRadius: "var(--radius-pill)", background: "var(--green)", color: "#fff" };

export default function HiringSignals() {
  const [posts, setPosts] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = () => hiringPosts().then((d) => setPosts(d.posts || [])).catch(() => {});
  useEffect(() => { load(); }, []);

  const onRefresh = () => {
    setBusy(true); setError(null);
    refreshHiring().then(load).catch((e) => setError(e.message)).finally(() => setBusy(false));
  };
  const onDismiss = (id) => {
    setPosts((p) => p.filter((x) => x.id !== id));
    dismissHiring(id).catch(() => {});
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div style={{ fontSize: 13, color: "var(--ink-faint)" }}>
          Individual LinkedIn hiring posts from the last 24 hours, ranked for you.
        </div>
        <button style={BTN} onClick={onRefresh} disabled={busy}>
          {busy ? "Searching LinkedIn…" : "Refresh"}
        </button>
      </div>

      {error && (
        <div role="alert" style={{ color: "var(--dupe-ink)", background: "var(--dupe-bg)", borderRadius: 12, padding: "10px 14px", marginBottom: 12 }}>
          {error.includes("re-paste") ? "LinkedIn session expired — re-paste your cookies in .env." : error}
        </div>
      )}

      {posts.length === 0 && !busy && (
        <div style={{ fontSize: 12, color: "var(--ink-faint)", fontStyle: "italic" }}>
          No hiring posts in the last 24 hours. Hit Refresh to search LinkedIn.
        </div>
      )}

      {posts.map((p) => (
        <div key={p.id} style={{ border: "0.5px solid var(--hairline)", borderRadius: 12, padding: 12, marginBottom: 10, background: "var(--card)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>{p.poster_name}</div>
              <div style={{ fontSize: 12, color: "var(--ink-faint)" }}>{p.poster_headline}</div>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "flex-start", flexShrink: 0 }}>
              <span style={{ fontSize: 11, color: "var(--green)", fontWeight: 600 }}>
                {Math.round((p.fit_score || 0) * 100)}% fit
              </span>
              <button aria-label="Dismiss" onClick={() => onDismiss(p.id)}
                style={{ border: "none", background: "none", cursor: "pointer", color: "var(--ink-faint)" }}>×</button>
            </div>
          </div>
          <div style={{ fontSize: 13, color: "var(--ink-soft)", margin: "8px 0" }}>{p.text}</div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--ink-faint)" }}>
            <span>{p.keyword} · {p.posted_at || "recent"}</span>
            <a href={p.url} target="_blank" rel="noreferrer" style={{ color: "var(--green)" }}>View on LinkedIn ↗</a>
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Wire the third tab into `App.jsx`**

Import `HiringSignals`. Add a third `TabButton`:
```jsx
<TabButton active={activeTab === "hiring"} onClick={() => setActiveTab("hiring")} label="Hiring Signals" />
```
Extend the render branch (convert the two-way ternary to handle three tabs), e.g.:
```jsx
{activeTab === "hiring" ? (
  <HiringSignals />
) : activeTab === "browse" ? (
  /* existing browse block */
) : (
  /* existing tracker block */
)}
```

- [ ] **Step 6: Run tests + full frontend suite**

Run (from `frontend/`): `npx vitest run src/__tests__/hiring_signals.test.jsx && npx vitest run`
Expected: new tests PASS; all prior frontend tests still pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/HiringSignals.jsx frontend/src/App.jsx frontend/src/api.js frontend/src/__tests__/hiring_signals.test.jsx
git commit -m "feat(ui): Hiring Signals tab (refresh/list/dismiss, fit badge, 24h)"
```

---

### Task 7: Runbook + live e2e + finish

**Files:**
- Create: `docs/linkedin-hiring-runbook.md`
- Test: `tests/test_hiring_live.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the guarded live e2e test**

```python
# tests/test_hiring_live.py
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("LINKEDIN_LI_AT"), reason="no LinkedIn cookie in env"
)


def test_live_search_returns_list():
    from job_dashboard.linkedin.voyager import VoyagerClient
    c = VoyagerClient(os.environ["LINKEDIN_LI_AT"], os.environ["LINKEDIN_JSESSIONID"])
    assert c.me().get("included") is not None
    posts = c.search_posts("hiring ML engineer")
    assert isinstance(posts, list)  # >=0; real content varies day to day
```

- [ ] **Step 2: Run it with the cookie loaded**

```bash
python3 -c "import sys;sys.path.insert(0,'src');from job_dashboard.env import load_env_file;load_env_file('.env')" \
  && LINKEDIN_LI_AT=$(python3 -c "import sys,os;sys.path.insert(0,'src');from job_dashboard.env import load_env_file;load_env_file('.env');print(os.environ['LINKEDIN_LI_AT'])") \
     LINKEDIN_JSESSIONID=$(python3 -c "import sys,os;sys.path.insert(0,'src');from job_dashboard.env import load_env_file;load_env_file('.env');print(os.environ['LINKEDIN_JSESSIONID'])") \
     python3 -m pytest tests/test_hiring_live.py -v
```
Expected: PASS (or SKIP if cookie absent). Keep to a single run.

- [ ] **Step 3: Write `docs/linkedin-hiring-runbook.md`**

Document: (a) how to extract `li_at` + `JSESSIONID` from the browser (DevTools → Application → Cookies → linkedin.com; `JSESSIONID` includes the `ajax:` quotes); (b) the `.env` var names; (c) that it's read-only, personal, low-volume, and LinkedIn ToS discourages scraping — use responsibly; (d) cookies expire (~monthly) → the tab shows "session expired — re-paste"; (e) how to use: open the Hiring Signals tab, click Refresh. Keep under 120 lines.

- [ ] **Step 4: Full suites + live dashboard smoke**

Run: `python3 -m pytest -q` and (from `frontend/`) `npx vitest run`.
Then start the server, open the Hiring Signals tab, click Refresh, confirm posts render (or a clear empty/expired state). Screenshot for the user.

- [ ] **Step 5: Commit**

```bash
git add docs/linkedin-hiring-runbook.md tests/test_hiring_live.py
git commit -m "docs+test: LinkedIn hiring runbook + guarded live e2e"
```

---

## Self-Review

- **Spec coverage:** individual posts (Tasks 3-4) ✓; separate tab (Task 6) ✓; 24h window (Tasks 1,3) ✓; cookie auth + csrf rule (Task 2) ✓; auto-resolved queryId (Task 3) ✓; profile ranking (Task 4) ✓; dedup by url (Tasks 1,4) ✓; refresh/list/dismiss API (Task 5) ✓; expiry→clear message (Tasks 2,5,6) ✓; runbook + live e2e (Task 7) ✓; read-only/low-volume (Global Constraints) ✓.
- **Type consistency:** `HiringPost` fields match the `hiring_posts` columns and the `upsert_hiring_post` dict keys (`url, poster_name, poster_headline, text, posted_at, keyword, fit_score` + `fetched_at` added in `run_digest`). `search_posts` return (list of raw dicts) feeds `parse_post`. `build_hiring_router(db_path, hiring_client, embed_model)` matches the `create_app` kwargs and the test's `create_app(...)` call.
- **External-shape risk:** the raw post object shape (Task 4 `parse_post`) and the GraphQL variable encoding (Task 3) are confirmed by Task 3's live-verification step; the fixtures are adjusted to the real shape there, and `parse_post`'s never-raise invariant makes downstream robust regardless.
