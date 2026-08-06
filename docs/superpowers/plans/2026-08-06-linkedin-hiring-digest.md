# LinkedIn Hiring Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily digest of individual LinkedIn "who's hiring" posts for the candidate's target roles, in a separate "Hiring Signals" tab, limited to the last 24 hours and ranked against the candidate's profile.

**Architecture:** Raw-HTTP against LinkedIn is bot-walled (Cloudflare JS challenge), so a **Selenium-driven real Chrome** — authenticated with the candidate's own `li_at`/`JSESSIONID` cookies — loads each keyword's content-search page (past-24h), scrolls with human-paced random delays, and hands the rendered HTML to a pure BeautifulSoup parser. An orchestrator dedups, ranks (reusing `match/embedder.py`), and stores posts in a `hiring_posts` table. A `/api/hiring/*` router (injectable fetcher) serves a new React "Hiring Signals" tab.

**Tech Stack:** Python 3.11, FastAPI, sqlite3, pytest; **Selenium 4 + BeautifulSoup** for fetching/parsing; sentence-transformers (existing); React + Vite + Vitest.

## Global Constraints

- Python 3.11, pytest; React/Vite/Vitest; every file under 500 lines.
- New deps: `selenium`, `beautifulsoup4` in `requirements.txt`; Chrome installed (Selenium 4 auto-manages the driver). `selenium` is imported **lazily** inside the default driver factory (like `embedder.load_default_model` lazily imports sentence-transformers), so importing/testing the modules needs neither Selenium nor a browser.
- Cookies (`LINKEDIN_LI_AT`, `LINKEDIN_JSESSIONID`) live in `.env` only — never logged, never committed. `env.py` strips surrounding quotes on load.
- **Read-only, human-paced, low-volume, no login automation, no writes to LinkedIn.** Randomized delays between actions; a few gentle scrolls; one search per keyword per manual refresh.
- **All Selenium is behind an injectable `driver_factory`, and delays behind an injectable `sleep`**, so the whole suite runs with no browser and no network. Live paths are `skipif not os.getenv("LINKEDIN_LI_AT")`-guarded and run sparingly.
- Pure functions take timestamps as inputs (`fetched_at`) — no hidden clock calls in engine logic.
- Reuse existing seams: `match/embedder.py` (`load_default_model`, `cosine`), `match/profile_text.py` (`compose_profile_text`), `env.py`, the ui-v2 `activeTab` tab shell, the `build_*_router(db_path, engine=None)` injected-engine API pattern.
- Commits must NOT contain a `Co-Authored-By` trailer (repo rule).

---

### Task 1: `hiring_posts` table + CRUD  ✅ DONE (commit 5c6c349)

Implemented as `db_hiring.py` (`_ensure_hiring_posts_table`, `upsert_hiring_post`, `hiring_posts(within_hours=24)`, `dismiss_hiring_post`), re-exported from `db.py`. Dedup on `url`, 24h window on `fetched_at`, `dismissed` preserved across re-upsert. Tests in `tests/test_hiring_db.py` (4 pass). **No action needed** — later tasks import these from `job_dashboard.db`.

---

### Task 2: `post_parse.py` — rendered-HTML → post dicts (pure)

**Files:**
- Create: `src/job_dashboard/linkedin/post_parse.py`
- Test: `tests/test_post_parse.py`

**Interfaces:**
- Consumes: `beautifulsoup4` only.
- Produces: `parse_posts_html(html: str) -> list[dict]` — each dict `{url, poster_name, poster_headline, text, posted_at}`. Never raises; skips any card missing `url` or `text`.

**Note on selectors:** LinkedIn's rendered markup is confirmed against real HTML in Task 3's live step. Implement against the structure in the fixture below; if Task 3 finds the real DOM differs, adjust selectors here and update the fixture. Invariant regardless: `parse_posts_html` never raises and drops cards missing url/text.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_post_parse.py
from job_dashboard.linkedin.post_parse import parse_posts_html

# Minimal shape mirroring a rendered content-search result card.
FIXTURE = """
<div data-view-name="feed-full-update" data-urn="urn:li:activity:12345">
  <a class="update-components-actor__meta-link" href="https://www.linkedin.com/in/jane">
    <span class="update-components-actor__title"><span>Jane Doe</span></span>
    <span class="update-components-actor__description">Engineering Manager @ Acme</span>
    <span class="update-components-actor__sub-description">5h • Edited</span>
  </a>
  <div class="update-components-text">We're hiring an ML Engineer! DM me.</div>
</div>
<div data-view-name="feed-full-update" data-urn="urn:li:activity:67890">
  <div class="update-components-text">No actor/url here — should be skipped</div>
</div>
"""


def test_parses_one_valid_card():
    posts = parse_posts_html(FIXTURE)
    assert len(posts) == 1                      # second card missing url/name skipped
    p = posts[0]
    assert p["poster_name"] == "Jane Doe"
    assert "ML Engineer" in p["text"]
    assert p["url"].endswith("/activity:12345") or "12345" in p["url"]
    assert "Acme" in p["poster_headline"]
    assert "5h" in (p["posted_at"] or "")


def test_garbage_html_returns_empty_never_raises():
    assert parse_posts_html("") == []
    assert parse_posts_html("<html><body>nothing</body></html>") == []
    assert parse_posts_html("<div data-view-name='feed-full-update'></div>") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_post_parse.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `linkedin/post_parse.py`**

```python
"""Parse a rendered LinkedIn content-search page into post dicts.

Pure BeautifulSoup — no browser, no network. This is where LinkedIn markup
changes are absorbed (Task 3's live step verifies the selectors against real
rendered HTML). Never raises; a card missing url or text is skipped.
"""
from __future__ import annotations

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
    return a.get("href") if a and a.get("href") else None


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
    try:
        soup = BeautifulSoup(html or "", "html.parser")
    except Exception:  # noqa: BLE001
        return []
    out = []
    for card in soup.select(_CARD_SELECTOR):
        post = _one(card)
        if post is not None:
            out.append(post)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_post_parse.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/linkedin/post_parse.py tests/test_post_parse.py
git commit -m "feat(linkedin): parse rendered search HTML into post dicts (pure, never-raise)"
```

---

### Task 3: `browser_fetch.py` — Selenium fetcher

**Files:**
- Create: `src/job_dashboard/linkedin/browser_fetch.py`
- Test: `tests/test_browser_fetch.py`

**Interfaces:**
- Consumes: `parse_posts_html` (Task 2); `selenium` (lazy, only in the default driver factory).
- Produces:
  - `class LinkedInAuthError(RuntimeError)`
  - `class LinkedInBrowserFetcher(li_at, jsessionid, *, driver_factory=None, headless=False, max_scrolls=3, sleep=None)` with `.search_posts(keyword, *, date_posted="past-24h") -> list[dict]`.

- [ ] **Step 1: Write the failing test (fake driver — no browser)**

```python
# tests/test_browser_fetch.py
import pytest
from job_dashboard.linkedin.browser_fetch import (
    LinkedInBrowserFetcher, LinkedInAuthError,
)

CARD = """
<div data-view-name="feed-full-update" data-urn="urn:li:activity:1">
  <span class="update-components-actor__title"><span>Jane Doe</span></span>
  <span class="update-components-actor__description">EM @ Acme</span>
  <div class="update-components-text">Hiring an ML Engineer!</div>
</div>"""


class FakeDriver:
    def __init__(self, page_source, current_url="https://www.linkedin.com/search/results/content/"):
        self.page_source = page_source
        self.current_url = current_url
        self.calls = []
    def get(self, url): self.calls.append(("get", url))
    def add_cookie(self, c): self.calls.append(("cookie", c["name"]))
    def execute_script(self, *a, **k): self.calls.append(("scroll",))
    def quit(self): self.calls.append(("quit",))


def _fetcher(driver):
    return LinkedInBrowserFetcher(
        "LIAT", "ajax:1",
        driver_factory=lambda: driver,
        sleep=lambda *_: None,          # no real delays in tests
        max_scrolls=2,
    )


def test_search_returns_parsed_posts_and_injects_cookies():
    d = FakeDriver(CARD)
    posts = _fetcher(d).search_posts("hiring ML engineer")
    assert len(posts) == 1 and posts[0]["poster_name"] == "Jane Doe"
    # cookies injected and driver cleaned up
    assert ("cookie", "li_at") in d.calls and ("cookie", "JSESSIONID") in d.calls
    assert ("quit",) in d.calls


def test_login_redirect_raises_auth_error():
    d = FakeDriver("<html>Sign in</html>", current_url="https://www.linkedin.com/login")
    with pytest.raises(LinkedInAuthError):
        _fetcher(d).search_posts("hiring ML engineer")
    assert ("quit",) in d.calls           # still cleaned up on error


def test_driver_always_quit_even_if_parse_empty():
    d = FakeDriver("<html>no cards</html>")
    assert _fetcher(d).search_posts("x") == []
    assert ("quit",) in d.calls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_browser_fetch.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `linkedin/browser_fetch.py`**

```python
"""Selenium-driven LinkedIn content-search fetcher (read-only).

Raw HTTP to LinkedIn is Cloudflare-bot-walled; a real Chrome executes the JS
challenge and loads normally. We authenticate with the candidate's own cookies
(no password, no login automation), navigate the content-search page per
keyword, scroll with human-paced random delays, and parse the rendered HTML.
Selenium is imported lazily so the module imports/tests without a browser.
Never logs cookie values.
"""
from __future__ import annotations

import random
import time
import urllib.parse

from job_dashboard.linkedin.post_parse import parse_posts_html

_LOGIN_MARKERS = ("/login", "/authwall", "/checkpoint", "/uas/login")


class LinkedInAuthError(RuntimeError):
    """Cookies missing/expired — session landed on a login/authwall page."""


def _default_driver_factory(headless: bool):
    def factory():
        from selenium import webdriver  # lazy: no selenium needed for unit tests
        opts = webdriver.ChromeOptions()
        if headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--window-size=1280,900")
        opts.add_argument(
            "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
        return webdriver.Chrome(options=opts)
    return factory


class LinkedInBrowserFetcher:
    def __init__(self, li_at, jsessionid, *, driver_factory=None, headless=False,
                 max_scrolls=3, sleep=None):
        self._li_at = li_at
        self._jsessionid = str(jsessionid).strip().strip('"')
        self._driver_factory = driver_factory or _default_driver_factory(headless)
        self._max_scrolls = max_scrolls
        self._sleep = sleep or (lambda: time.sleep(random.uniform(2.0, 5.0)))

    def _nap(self):
        # tolerate both no-arg and value styles of injected sleep
        try:
            self._sleep()
        except TypeError:
            self._sleep(0)

    def search_posts(self, keyword, *, date_posted="past-24h"):
        driver = self._driver_factory()
        try:
            driver.get("https://www.linkedin.com")
            for name, value in (("li_at", self._li_at),
                                ("JSESSIONID", f'"{self._jsessionid}"')):
                driver.add_cookie({"name": name, "value": value,
                                   "domain": ".linkedin.com"})
            self._nap()
            kw = urllib.parse.quote(keyword)
            driver.get(
                "https://www.linkedin.com/search/results/content/"
                f"?keywords={kw}&datePosted=%22{date_posted}%22&origin=FACETED_SEARCH")
            self._nap()
            if any(m in (driver.current_url or "") for m in _LOGIN_MARKERS):
                raise LinkedInAuthError(
                    "LinkedIn session expired — re-paste li_at/JSESSIONID from your browser")
            for _ in range(self._max_scrolls):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                self._nap()
            return parse_posts_html(driver.page_source)
        finally:
            try:
                driver.quit()
            except Exception:  # noqa: BLE001
                pass
```

- [ ] **Step 4: Run unit tests to verify they pass**

Run: `python3 -m pytest tests/test_browser_fetch.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Live verification (Chrome + cookie required; run SPARINGLY)**

Only if Chrome + `selenium` are installed and `.env` has cookies. This opens a real browser window.

```bash
python3 -c "
import os, sys; sys.path.insert(0,'src')
from job_dashboard.env import load_env_file; load_env_file('.env')
from job_dashboard.linkedin.browser_fetch import LinkedInBrowserFetcher
f = LinkedInBrowserFetcher(os.environ['LINKEDIN_LI_AT'], os.environ['LINKEDIN_JSESSIONID'])
posts = f.search_posts('hiring ML engineer')
print('posts parsed:', len(posts))
if posts: print({k: (v[:60] if isinstance(v,str) else v) for k,v in posts[0].items()})
"
```
Expected: opens Chrome, lands logged-in on the search page, prints a post count and a sample. **If 0 posts but no error**, the selectors don't match the live DOM — inspect the rendered card markup, fix the selectors in `post_parse.py`, update its fixture/test, and re-run **once**. Do NOT loop many live runs. Record the real card structure in the report.

- [ ] **Step 6: Commit**

```bash
git add src/job_dashboard/linkedin/browser_fetch.py tests/test_browser_fetch.py
git commit -m "feat(linkedin): Selenium content-search fetcher (cookie auth, human-paced, injectable driver)"
```

---

### Task 4: Digest orchestration (normalize, rank, run)

**Files:**
- Create: `src/job_dashboard/linkedin/hiring_digest.py`
- Test: `tests/test_hiring_digest.py`

**Interfaces:**
- Consumes: `upsert_hiring_post` (from `job_dashboard.db`, Task 1); a fetcher with `.search_posts(keyword) -> list[dict]` (Task 3); `cosine` from `match/embedder.py`.
- Produces: `KEYWORDS: list[str]`; `@dataclass HiringPost`; `to_hiring_post(d, keyword) -> HiringPost | None`; `rank_post(text, profile_vec, model) -> float`; `run_digest(conn, fetcher, keywords, profile_text, *, embed_model=None, fetched_at, on_progress=None) -> list[HiringPost]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hiring_digest.py
from job_dashboard.linkedin.hiring_digest import (
    KEYWORDS, HiringPost, to_hiring_post, rank_post, run_digest,
)
from job_dashboard.db import init_db, hiring_posts

DICT_OK = {"url": "https://li/1", "poster_name": "Jane Doe",
           "poster_headline": "EM @ Acme", "text": "Hiring an ML Engineer!",
           "posted_at": "5h"}


class FakeModel:
    def encode(self, texts):
        return [[float(len(t)), 1.0] for t in texts]


class FakeFetcher:
    def __init__(self): self.seen = []
    def search_posts(self, keyword, **kw):
        self.seen.append(keyword)
        return [DICT_OK]


def test_keywords_role_specific():
    assert "hiring ML engineer" in KEYWORDS
    assert all(k != "machine learning" for k in KEYWORDS)


def test_to_hiring_post_ok_and_bad():
    p = to_hiring_post(DICT_OK, "hiring ML engineer")
    assert isinstance(p, HiringPost) and p.url == "https://li/1"
    assert to_hiring_post({"text": "no url"}, "k") is None
    assert to_hiring_post({}, "k") is None


def test_rank_post_cosine_range():
    m = FakeModel()
    assert 0.0 <= rank_post("post", m.encode(["profile"])[0], m) <= 1.0


def test_run_digest_dedups_and_stores(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    f = FakeFetcher()
    out = run_digest(conn, f, ["hiring ML engineer", "hiring data scientist"],
                     "profile text", embed_model=FakeModel(),
                     fetched_at="2026-08-06T00:00:00+00:00")
    stored = hiring_posts(conn, within_hours=24)
    assert len(stored) == 1                       # same url from 2 keywords deduped
    assert f.seen == ["hiring ML engineer", "hiring data scientist"]
    assert isinstance(out, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_hiring_digest.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `linkedin/hiring_digest.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_hiring_digest.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/linkedin/hiring_digest.py tests/test_hiring_digest.py
git commit -m "feat(linkedin): digest orchestration (normalize/rank/dedup/store, KEYWORDS)"
```

---

### Task 5: `/api/hiring/*` router + wiring

**Files:**
- Create: `src/job_dashboard/api/hiring_routes.py`
- Modify: `src/job_dashboard/api/app.py` (build + include), `src/job_dashboard/api/serve.py` (build the real fetcher from env)
- Test: `tests/test_hiring_api.py`

**Interfaces:**
- Consumes: `run_digest`, `KEYWORDS` (Task 4); `hiring_posts`, `dismiss_hiring_post`, `init_db` (Task 1); `compose_profile_text` (`match/profile_text.py`); `LinkedInAuthError`, `LinkedInBrowserFetcher` (Task 3); `load_default_model` (`match/embedder.py`).
- Produces: `build_hiring_router(db_path, hiring_fetcher=None, embed_model=None) -> APIRouter`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hiring_api.py
from fastapi.testclient import TestClient
from job_dashboard.api.app import create_app

DICT_OK = {"url": "https://li/1", "poster_name": "Jane Doe",
           "poster_headline": "EM @ Acme", "text": "Hiring an ML Engineer!",
           "posted_at": "5h"}


class FakeFetcher:
    def search_posts(self, keyword, **kw): return [DICT_OK]


class FakeModel:
    def encode(self, texts): return [[float(len(t)), 1.0] for t in texts]


def _client(tmp_path, fetcher=None):
    db = str(tmp_path / "t.db")
    app = create_app(db_path=db, hiring_fetcher=fetcher or FakeFetcher(),
                     embed_model=FakeModel())
    return TestClient(app)


def test_refresh_then_list(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/hiring/refresh")
    assert r.status_code == 200 and r.json()["ranked"] >= 1
    posts = c.get("/api/hiring/posts").json()["posts"]
    assert posts[0]["poster_name"] == "Jane Doe" and posts[0]["url"] == "https://li/1"


def test_dismiss(tmp_path):
    c = _client(tmp_path)
    c.post("/api/hiring/refresh")
    pid = c.get("/api/hiring/posts").json()["posts"][0]["id"]
    assert c.post(f"/api/hiring/posts/{pid}/dismiss").status_code == 200
    assert c.get("/api/hiring/posts").json()["posts"] == []


def test_refresh_auth_error_returns_503(tmp_path):
    from job_dashboard.linkedin.browser_fetch import LinkedInAuthError

    class Dead:
        def search_posts(self, keyword, **kw):
            raise LinkedInAuthError("LinkedIn session expired — re-paste ...")

    c = _client(tmp_path, fetcher=Dead())
    r = c.post("/api/hiring/refresh")
    assert r.status_code == 503 and "re-paste" in r.json()["detail"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_hiring_api.py -v`
Expected: FAIL (`create_app` has no `hiring_fetcher` kwarg / 404).

- [ ] **Step 3: Write `api/hiring_routes.py`**

```python
"""Hiring-digest API: refresh (Selenium search), list, dismiss. Own router to
respect the 500-line cap; ``create_app`` includes it."""
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from job_dashboard.db import (
    init_db, hiring_posts as db_hiring_posts, dismiss_hiring_post,
)
from job_dashboard.linkedin.hiring_digest import KEYWORDS, run_digest
from job_dashboard.linkedin.browser_fetch import LinkedInAuthError
from job_dashboard.match.profile_text import compose_profile_text


def build_hiring_router(db_path, hiring_fetcher=None, embed_model=None) -> APIRouter:
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
        if hiring_fetcher is None:
            raise HTTPException(status_code=503,
                                detail="LinkedIn fetcher not configured — set cookies in .env")
        try:
            profile_text = compose_profile_text().text
        except Exception:
            profile_text = ""
        try:
            with db() as conn:
                ranked = run_digest(
                    conn, hiring_fetcher, KEYWORDS, profile_text,
                    embed_model=embed_model,
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                )
        except LinkedInAuthError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:  # browser/driver failure → clear 503, not a 500
            raise HTTPException(status_code=503,
                                detail=f"LinkedIn fetch failed: {e}")
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

- [ ] **Step 4: Wire into `create_app` and `serve.py`**

`api/app.py`: import `build_hiring_router`; add `hiring_fetcher=None, embed_model=None` params to `create_app`; near the other `include_router` calls add:
```python
    app.include_router(build_hiring_router(db_path, hiring_fetcher, embed_model))
```

`api/serve.py` (where `.env` is loaded): build the real fetcher + model and pass them in (adapt to the existing `create_app(...)` call — add only these two kwargs):
```python
    import os
    from job_dashboard.linkedin.browser_fetch import LinkedInBrowserFetcher
    from job_dashboard.match.embedder import load_default_model
    _li, _js = os.getenv("LINKEDIN_LI_AT"), os.getenv("LINKEDIN_JSESSIONID")
    hiring_fetcher = LinkedInBrowserFetcher(_li, _js) if _li and _js else None
    try:
        embed_model = load_default_model()
    except Exception:
        embed_model = None
    # ... create_app(db_path=..., hiring_fetcher=hiring_fetcher, embed_model=embed_model)
```

- [ ] **Step 5: Run tests + full suite**

Run: `python3 -m pytest tests/test_hiring_api.py -v && python3 -m pytest -q`
Expected: new tests PASS; no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/job_dashboard/api/hiring_routes.py src/job_dashboard/api/app.py src/job_dashboard/api/serve.py tests/test_hiring_api.py
git commit -m "feat(api): /api/hiring refresh/list/dismiss (injectable fetcher, auth error -> 503)"
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

const POSTS = { posts: [
  { id: 1, url: "https://li/1", poster_name: "Jane Doe", poster_headline: "EM @ Acme",
    text: "Hiring an ML Engineer!", posted_at: "5h", keyword: "hiring ML engineer",
    fit_score: 0.82 },
]};

beforeEach(() => {
  global.fetch = vi.fn((url) => {
    if (String(url).includes("/refresh")) return Promise.resolve({ ok: true, json: () => Promise.resolve({ ranked: 1 }) });
    if (String(url).includes("/dismiss")) return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
    return Promise.resolve({ ok: true, json: () => Promise.resolve(POSTS) });
  });
});

test("lists posts with poster and blurb", async () => {
  render(<HiringSignals />);
  await waitFor(() => expect(screen.getByText("Jane Doe")).toBeInTheDocument());
  expect(screen.getByText(/Hiring an ML Engineer/)).toBeInTheDocument();
});

test("refresh triggers POST /refresh", async () => {
  render(<HiringSignals />);
  fireEvent.click(screen.getByText(/Refresh/i));
  await waitFor(() =>
    expect(global.fetch.mock.calls.some(([u]) => String(u).includes("/refresh"))).toBe(true));
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
Extend the render branch to three tabs:
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

### Task 7: Deps + runbook + live e2e + finish

**Files:**
- Modify: `requirements.txt` (add `selenium`, `beautifulsoup4`)
- Create: `docs/linkedin-hiring-runbook.md`
- Test: `tests/test_hiring_live.py`

- [ ] **Step 1: Add dependencies**

Append to `requirements.txt`:
```
selenium
beautifulsoup4
```
Run: `pip3 install selenium beautifulsoup4` (and confirm Chrome is installed).

- [ ] **Step 2: Write the guarded live e2e test**

```python
# tests/test_hiring_live.py
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("LINKEDIN_LI_AT"), reason="no LinkedIn cookie in env"
)


def test_live_search_returns_list():
    from job_dashboard.linkedin.browser_fetch import LinkedInBrowserFetcher
    f = LinkedInBrowserFetcher(os.environ["LINKEDIN_LI_AT"],
                               os.environ["LINKEDIN_JSESSIONID"], headless=True)
    posts = f.search_posts("hiring ML engineer")
    assert isinstance(posts, list)   # >=0; content varies day to day
```

- [ ] **Step 3: Run it (opens a browser; run once)**

```bash
LINKEDIN_LI_AT=$(python3 -c "import sys,os;sys.path.insert(0,'src');from job_dashboard.env import load_env_file;load_env_file('.env');print(os.environ.get('LINKEDIN_LI_AT',''))") \
LINKEDIN_JSESSIONID=$(python3 -c "import sys,os;sys.path.insert(0,'src');from job_dashboard.env import load_env_file;load_env_file('.env');print(os.environ.get('LINKEDIN_JSESSIONID',''))") \
python3 -m pytest tests/test_hiring_live.py -v
```
Expected: PASS (or SKIP if no cookie / Selenium not installed). Run once — don't hammer LinkedIn.

- [ ] **Step 4: Write `docs/linkedin-hiring-runbook.md`**

Document (under ~120 lines): (a) extract `li_at`+`JSESSIONID` from the browser (DevTools → Application → Cookies → linkedin.com); (b) `.env` var names; (c) install: `pip3 install selenium beautifulsoup4` + Chrome required; (d) how it works — a real Chrome window opens during Refresh, searches each keyword, closes; (e) it's **read-only, personal, human-paced, low-volume**; LinkedIn ToS discourages scraping — use responsibly, don't run unattended/24-7; over-use can soft-flag the session (clears itself); (f) cookies expire (~monthly) → the tab shows "session expired — re-paste"; (g) usage: open the Hiring Signals tab → Refresh (takes a couple minutes across all keywords).

- [ ] **Step 5: Full suites + dashboard smoke**

Run: `python3 -m pytest -q` and (from `frontend/`) `npx vitest run`.
Then start the server, open the Hiring Signals tab, click Refresh, confirm posts render (or a clear empty/expired state). Screenshot for the user.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt docs/linkedin-hiring-runbook.md tests/test_hiring_live.py
git commit -m "docs+deps: Selenium/bs4 deps + LinkedIn hiring runbook + guarded live e2e"
```

---

## Self-Review

- **Spec coverage:** real-browser fetch beating the bot wall (Tasks 2-3) ✓; separate tab (Task 6) ✓; 24h window (Tasks 1,3) ✓; cookie auth via Selenium, no login automation (Task 3) ✓; profile ranking (Task 4) ✓; dedup by url (Tasks 1,4) ✓; refresh/list/dismiss API (Task 5) ✓; expiry→clear message (Tasks 3,5,6) ✓; deps + runbook + live e2e (Task 7) ✓; human-paced/low-volume + injectable driver so tests need no browser (Global Constraints) ✓.
- **Type consistency:** `parse_posts_html` returns `list[dict]{url,poster_name,poster_headline,text,posted_at}` → consumed by `LinkedInBrowserFetcher.search_posts` → `to_hiring_post` maps the same keys to `HiringPost` → `asdict(post) + fetched_at` matches `upsert_hiring_post`'s expected keys (from Task 1). `build_hiring_router(db_path, hiring_fetcher, embed_model)` matches the `create_app` kwargs and the test's `create_app(...)` call. The fetcher's `.search_posts(keyword)` interface is identical in Task 3 (produces), Task 4 (`run_digest` consumes), and Task 5 (fake fetcher).
- **External-shape risk:** the live DOM selectors (`post_parse.py`) are verified in Task 3's live step and the fixtures adjusted to real rendered HTML; `parse_posts_html`/`to_hiring_post` never-raise invariants keep the pipeline robust regardless.
- **Superseded:** the earlier Voyager HTTP client (old Tasks 2-3) is removed — raw HTTP is Cloudflare-bot-walled; ledger records the finding.
