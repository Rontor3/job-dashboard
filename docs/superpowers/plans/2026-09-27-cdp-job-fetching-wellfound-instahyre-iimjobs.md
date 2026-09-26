# CDP Job Fetching: Wellfound, Instahyre, IIMJobs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the remaining three browser job sources (Wellfound, Instahyre, IIMJobs) to Refresh, each behind its own off-by-default switch, on top of one new guarded session capability: a same-origin `fetch`.

**Architecture:** `CdpSession.fetch(url, *, hosts, ...)` runs a `fetch()` inside the session's own tab (cookies included), host-allowlisted, capped, paced, and **any non-200 raises `Blocked`**. `Capture.exchanges()` lets an adapter read the page's own request headers/body once (Wellfound's signed operation). Three adapters (`wellfound.py`, `instahyre.py`, `iimjobs.py`) follow the shape of `linkedin.py`/`naukri.py`: `run(session, ctx) -> list[JobListing]`. Spec: `docs/career-agent/2026-09-25-cdp-job-fetching-design.md` (per-site sections + "Round 3").

**Prerequisite:** the Naukri plan's Task 1 is done first (`docs/superpowers/plans/2026-09-27-cdp-job-fetching-naukri.md`): it adds `runner.WINDOWS`, `runner.LIMITS_BY_SITE`, `AdapterContext.known_text`, `norm_text` in `types.py`, and the generalised `_window`. This plan reuses them. (`html_to_text` lives in `types.py`; the Naukri plan's Task 2 adds it. If Naukri Task 2 is not built yet when you reach this plan's Task 1, add it there — it is defined once.)

**Tech Stack:** Python 3, sqlite3, Playwright via `CdpSession`, FastAPI, pytest.

## Global Constraints

- Run tests: `PYTHONPATH=src python3 -m pytest tests/<file> -q`. Tests never touch a browser/network; live smokes only with `RUN_CDP_TESTS=1`.
- All three sites default OFF: `browser_wellfound_enabled`, `browser_instahyre_enabled`, `browser_iimjobs_enabled` = `"0"`. 48h minimum interval per site (existing).
- Same-origin `fetch` is the only new capability. It must: check the host against the adapter's `hosts` (else `ValueError`), count toward the per-run cap, nap like a page load, raise `Blocked` on **any** non-200, never retry. Headers captured from the page stay in memory (never stored, logged or returned in `SiteResult`).
- No login, no captcha, no clicks/typing, never open Apply, never open Wellfound job detail pages (they emit a tracked view on the real account), never touch Instahyre "Interested"/apply.
- Caps per run (page loads + fetches): Wellfound incremental 25 / backfill 40; Instahyre incremental 30 / backfill 90; IIMJobs 40. Pacing 6-12 s (session default).
- Retention: nothing older than 30 days is inserted (backfill window 720 h).
- Keys: `external_id` is the site's numeric job id; `source` is the lowercase site name. Files < 500 lines. Stage only files named per task (other sessions have uncommitted edits — never `git add -A`).

## Verified shapes (live 2026-09-27; fixtures below are synthetic copies of these fields)

- **Instahyre:** `GET /api/v1/job_search?company_size=0&isLandingPage=true&job_type=0&offset=<20*(p-1)>&skills=<term>` → `{"meta": {"total_count": int}, "objects": [{id, title, candidate_title, employer: {company_name}, locations (str), keywords, public_url, ...}]}`; the search page fires offset 0 itself. Detail `GET /job-<id>-x/` (HTML) contains `"datePosted": "YYYY-MM-DD"` and a JSON-LD `JobPosting` with `description` (HTML). Ids rise with date. Apply is always in-site → `native`.
- **IIMJobs:** `GET https://gladiator.iimjobs.com/job/search?query=<term>&page=<n from 0>&posting=<days>` with header `version: 2` → `{"data": [{id, title, jobdesignation, createdTimeMs, jobDetailUrl, applyStatus, applyUrl, companyData: {companyName}, locations: [{name}], workFromHome}], "hasMore": bool}`; detail `GET https://gladiator.iimjobs.com/job/detail?jobcode=<id>` → `{"data": {"introText": "<html>", ...}}`. `applyUrl` non-empty ⇒ external.
- **Wellfound:** page `/jobs` fires POST `https://wellfound.com/graphql` with `{"operationName": "JobSearchResultsX", "variables": {"filterConfigurationInput": {...}}, "extensions": {"operationId": "<hash>"}}` and signed headers (`x-apollo-signature`, `x-wf-cfp`, `x-angellist-dd-client-referrer-resource`, `x-requested-with`, `apollographql-client-name`, `content-type`). Response: `data.talent.jobSearchResults = {totalStartupCount, hasNextPage, startups: {edges: [{node: {name, startupId, slug, highlightedJobListings: [{id, slug, title, description, liveStartAt (epoch seconds), autoPosted, locationNames}]}}]}}` (≤3 jobs per startup, ~22 jobs/page). India tag id `"1647"`. `autoPosted == true` ⇒ external (no URL available), else native.

## File Structure

| File | Responsibility |
|---|---|
| `sources/cdp/session.py` | `fetch`, `Capture.exchanges` |
| `sources/cdp/types.py` | `AdapterContext.anchor/save_anchor`, `html_to_text` |
| `sources/cdp/state.py` | `record_run(..., anchor=)` |
| `sources/cdp/{instahyre,iimjobs,wellfound}.py` | adapters |
| `sources/cdp/runner.py`, `qa_store.py`, `api/qa_routes.py` | registration, limits, windows, flags |
| `tests/cdp_fakes.py` + one `tests/test_cdp_*.py` per module | tests |

---

### Task 1: `CdpSession.fetch` and `Capture.exchanges`

**Files:** Modify `src/job_dashboard/sources/cdp/session.py`, `types.py` (add `html_to_text`), `tests/cdp_fakes.py`; Test `tests/test_cdp_session_fetch.py`

**Interfaces:**
- Produces: `CdpSession.fetch(url, *, hosts, method="GET", headers=None, body=None) -> str` (response text; relative URLs resolve against the tab's current URL); `Capture.exchanges() -> Iterator[(request_headers: dict, request_body: dict|str|None, response_json)]` (gzip request bodies are decoded; JSON bodies parsed); `types.html_to_text(html) -> str`.
- Fakes: `FakeRequest(url, headers, body)` (`.headers`, `.all_headers()`, `.post_data_buffer`); `FakeResponse.request`; `FakePage` script items may be `(url, body)` or `(url, body, FakeRequest)`; `FakePage.fetch_handler(url, method, headers, body) -> (status, text)` and `FakePage.fetches` (list of `(url, method, headers, body)`); `FakePage.evaluate(js, arg=None)` routes `arg` calls to `fetch_handler`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_cdp_session_fetch.py
import gzip, json
import pytest
from job_dashboard.sources.cdp.types import Blocked, CapReached, html_to_text
from tests.cdp_fakes import FakePage, FakeRequest, make_session


def page_with(handler, url="https://www.instahyre.com/x"):
    p = FakePage(); p.fetch_handler = handler; p.url = url
    return p


def test_fetch_returns_text_and_resolves_relative_url():
    p = page_with(lambda u, m, h, b: (200, '{"ok": 1}'))
    with make_session(p) as s:
        assert s.fetch("/api/v1/job_search?x=1", hosts=("www.instahyre.com",)) == '{"ok": 1}'
    assert p.fetches == [("https://www.instahyre.com/api/v1/job_search?x=1", "GET", {}, None)]


def test_fetch_rejects_foreign_host_without_calling():
    p = page_with(lambda u, m, h, b: (200, ""))
    with make_session(p) as s:
        with pytest.raises(ValueError):
            s.fetch("https://evil.example/x", hosts=("www.instahyre.com",))
    assert p.fetches == []


@pytest.mark.parametrize("status", [401, 403, 404, 406, 429, 500])
def test_any_non_200_is_blocked(status):
    with make_session(page_with(lambda u, m, h, b: (status, "no"))) as s:
        with pytest.raises(Blocked):
            s.fetch("/a", hosts=("www.instahyre.com",))


def test_fetch_counts_toward_cap_and_naps():
    naps, p = [], page_with(lambda u, m, h, b: (200, "x"))
    from job_dashboard.sources.cdp.session import CdpSession
    with CdpSession("u", max_loads=2, nap=lambda: naps.append(1), connect=lambda u: (p, lambda: None)) as s:
        s.fetch("/a", hosts=("www.instahyre.com",)); s.fetch("/b", hosts=("www.instahyre.com",))
        with pytest.raises(CapReached):
            s.fetch("/c", hosts=("www.instahyre.com",))
    assert naps == [1]


def test_exchanges_parse_json_and_gzip_request_bodies():
    body = json.dumps({"operationName": "JobSearchResultsX"}).encode()
    req = FakeRequest("https://wellfound.com/graphql", {"x-apollo-signature": "sig"}, gzip.compress(body))
    p = FakePage({"https://a/": [("https://wellfound.com/graphql", {"data": 1}, req)]})
    with make_session(p) as s:
        with s.capture("graphql") as cap:
            s.goto("https://a/")
    assert list(cap.exchanges()) == [({"x-apollo-signature": "sig"}, {"operationName": "JobSearchResultsX"}, {"data": 1})]


def test_html_to_text():
    assert html_to_text("<p>Build <b>models</b></p><ul><li>Python</li></ul>&amp; more") == "Build models\nPython\n& more"
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Implement**

`types.py` (append; `re`/`html` imported at top):
```python
import html as _html
import re

def html_to_text(s: str) -> str:
    s = re.sub(r"(?i)<\s*(br|/p|/li|/div|/h\d)\s*/?>", "\n", s or "")
    s = _html.unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", s)).strip()
```
(Skip this block if the Naukri plan's Task 2 already added `html_to_text` to `types.py`.)

`session.py`:
```python
import gzip
import json
from urllib.parse import urljoin, urlparse

_FETCH_JS = ("async ([u, m, h, b]) => { const r = await fetch(u, {method: m, credentials: 'include', "
             "headers: h || {}, body: b}); return [r.status, await r.text()]; }")
```
`Capture.exchanges`:
```python
    def exchanges(self):
        """(request headers, request body parsed, response json) for each captured exchange that parses."""
        for r in self.responses:
            try:
                rq = r.request
                raw = rq.post_data_buffer
                if raw and raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = raw.decode("utf-8", "replace") if raw else None
                yield dict(rq.all_headers()), body, r.json()
            except Exception:
                continue
```
`CdpSession.fetch`:
```python
    def fetch(self, url, *, hosts, method="GET", headers=None, body=None) -> str:
        """Same-origin fetch inside our own tab. Host-allowlisted; counts toward the cap; any non-200 is a block."""
        absolute = urljoin(self._page.url or "", url)
        host = urlparse(absolute).hostname or ""
        if not any(host == h or host.endswith("." + h) for h in hosts):
            raise ValueError(f"host {host!r} not allowed")
        if self.loads >= self.max_loads:
            raise CapReached(f"{self.max_loads} page loads")
        if self.loads:
            self._nap()
        self.loads += 1
        status, text = self._page.evaluate(_FETCH_JS, [absolute, method, headers or {}, body])
        if status != 200:
            raise Blocked(f"HTTP {status} on {host}")
        return text
```
`tests/cdp_fakes.py`: add
```python
class FakeRequest:
    def __init__(self, url, headers, body=None):
        self.url, self.headers, self.post_data_buffer = url, headers, body

    def all_headers(self):
        return self.headers
```
in `FakeResponse.__init__` add `self.request = None`; in `FakePage.__init__` add `self.fetches, self.fetch_handler = [], None`; in `FakePage.goto` replace the inner loop with:
```python
                for item in resps:
                    ru, body, *rest = item
                    for h in list(self.handlers):
                        resp = FakeResponse(ru, body)
                        if rest:
                            resp.request = rest[0]
                        h(resp)
```
and `evaluate`:
```python
    def evaluate(self, js, arg=None):
        if arg is not None:
            u, m, h, b = arg
            self.fetches.append((u, m, h, b))
            return list(self.fetch_handler(u, m, h, b))
        return self.text
```
(`FakePage.url` is set by `goto`; the tests above set `p.url` directly.)

- [ ] **Step 4:** `pytest tests/test_cdp_session_fetch.py tests/test_cdp_session.py tests/test_cdp_naukri_parse.py -q` (skip missing files) → PASS. **Step 5: Commit** — `git add src/job_dashboard/sources/cdp/session.py src/job_dashboard/sources/cdp/types.py tests/cdp_fakes.py tests/test_cdp_session_fetch.py`; message `feat(cdp): guarded same-origin fetch and request exchanges on CdpSession`.

---

### Task 2: Runner plumbing — anchor, per-site enable flags

**Files:** Modify `types.py`, `state.py`, `runner.py`, `qa_store.py`, `api/qa_routes.py`; Test extend `tests/test_cdp_state.py`, `tests/test_cdp_runner.py`, `tests/test_cdp_settings_api.py`

**Interfaces:**
- Produces: `AdapterContext.anchor: int = 0`, `AdapterContext.save_anchor: Optional[Callable[[int], None]] = None`; `state.record_run(..., anchor=None)` (stores `str(anchor)` when given, else keeps the previous); `state.get_anchor(conn, site) -> int`; runner passes `anchor=state.get_anchor(...)` and `save_anchor` that persists immediately (so a run cut off by the cap keeps what it learned); `DEFAULT_SETTINGS` gains `browser_wellfound_enabled`, `browser_instahyre_enabled`, `browser_iimjobs_enabled` (all `"0"`); settings API get/put those three flags like the existing ones.

- [ ] **Step 1: Failing tests**
```python
# tests/test_cdp_state.py (append)
def test_anchor_roundtrip_and_kept_across_runs():
    c = conn()
    assert state.get_anchor(c, "instahyre") == 0
    state.record_run(c, "instahyre", ok=True, anchor=441000, now=T0)
    state.record_run(c, "instahyre", ok=True, now=T0 + timedelta(hours=49))
    assert state.get_anchor(c, "instahyre") == 441000
```
```python
# tests/test_cdp_runner.py (append)
def test_anchor_is_passed_in_and_saved_immediately():
    c = conn(); state.record_run(c, "linkedin", ok=True, anchor=100, backfill_done=True, now=None)
    got = {}
    def run(s, ctx):
        got["in"] = ctx.anchor; ctx.save_anchor(250); got["mid"] = state.get_anchor(c, "linkedin"); return []
    c.execute("UPDATE fetch_state SET last_success_at='2000-01-01T00:00:00+00:00'"); c.commit()   # make it due
    go(c, run)
    assert got == {"in": 100, "mid": 250}
```
```python
# tests/test_cdp_settings_api.py (append)
def test_new_site_switches_default_off_and_toggle(tmp_path):
    c = TestClient(create_app(str(tmp_path / "j.db"), pipeline_runner=lambda p, s: {}))
    for site in ("wellfound", "instahyre", "iimjobs"):
        key = f"browser_{site}_enabled"
        assert c.get("/api/agent-settings").json()[key] is False
        assert c.put("/api/agent-settings", json={key: True}).status_code == 200
        assert c.get("/api/agent-settings").json()[key] is True
```
- [ ] **Step 2:** FAIL. **Step 3: Implement** — `types.py` fields above; `state.py`: add `anchor` column to the table (already in `CREATE TABLE`; existing DBs have it), extend `record_run` with `anchor=None` and `anchor=COALESCE(?, fetch_state.anchor)` in the upsert (`str(anchor) if anchor is not None else None`), and:
```python
def get_anchor(conn, site: str) -> int:
    row = get(conn, site)
    try:
        return int(row["anchor"]) if row and row["anchor"] else 0
    except (TypeError, ValueError):
        return 0
```
`runner.py`: build `ctx` with `anchor=state.get_anchor(conn, site)` and
```python
def _save_anchor_fn(conn, site):
    def save(value):
        state.record_run_anchor(conn, site, int(value))
    return save
```
with `state.record_run_anchor(conn, site, anchor)` = `UPDATE fetch_state SET anchor=? WHERE site=?` after `INSERT OR IGNORE INTO fetch_state (site) VALUES (?)`. `qa_store.DEFAULT_SETTINGS`: three new keys. `qa_routes.py`: three `Optional[bool]` fields in `SettingsBody`; get/put handled by a loop over `("linkedin", "naukri", "wellfound", "instahyre", "iimjobs")` — refactor the existing LinkedIn/Naukri handling into that loop, keeping the response keys `browser_<site>_enabled`.
- [ ] **Step 4:** run `tests/test_cdp_state.py tests/test_cdp_runner.py tests/test_cdp_settings_api.py tests/test_qa_api.py -q` → PASS. **Step 5: Commit** `feat(cdp): anchor state, save_anchor callback, switches for Wellfound/Instahyre/IIMJobs`.

---

### Task 3: Instahyre adapter

**Files:** Create `src/job_dashboard/sources/cdp/instahyre.py`; Test `tests/test_cdp_instahyre.py`

**Interfaces:**
- Consumes: `session.goto/capture/fetch`, `AdapterContext(known, terms, max_pages, anchor, save_anchor, stats, redate?)`, `html_to_text`.
- Produces: `SITE = "instahyre"`, `HOSTS = ("www.instahyre.com",)`, `TERMS = ["machine learning engineer", "data scientist", "ai engineer", "llm engineer"]`; `parse_list(body) -> (cards, total)`; `parse_detail(html) -> {"date": date|None, "description": str}`; `to_listing(card, detail)`; `run(session, ctx, today=None)`.
- `run`: per term, page 1 via passive capture of `api/v1/job_search` on `goto(/search-jobs?skills=<term>)`; pages `2..ctx.max_pages` via `fetch(/api/v1/job_search?...&offset=20*(p-1))`, stopping a term on an empty page. Candidates deduped by id. Process ids **descending**: DB-known → `skipped_known`; `id <= ctx.anchor` → `stats["skipped_stale"]`; else `fetch(/job-<id>-x/)`; `date` older than 30 days → `ctx.anchor = max(...)`, `ctx.save_anchor(id)`, skip; no description → skip (not known); else listing. `CapReached` → `stats["capped"] = True`. `stats["pages"]` counts list pages that returned cards.

- [ ] **Step 1: Failing test**
```python
# tests/test_cdp_instahyre.py
import json
from datetime import date
from job_dashboard.sources.cdp import instahyre as ih
from job_dashboard.sources.cdp.types import AdapterContext
from tests.cdp_fakes import FakePage, make_session

TODAY = date(2026, 9, 27)


def obj(i, company="Acme", title="Data Scientist"):
    return {"id": i, "title": title, "employer": {"company_name": company}, "locations": "Bangalore",
            "keywords": ["ml"], "public_url": f"https://www.instahyre.com/job-{i}-data-scientist-at-acme-1/"}


def listing(ids, total=99):
    return {"meta": {"total_count": total}, "objects": [obj(i) for i in ids]}


def detail_html(posted, desc="<p>Build models</p>"):
    ld = json.dumps({"@context": "https://schema.org", "@type": "JobPosting", "description": desc})
    return f'<html><script type="application/ld+json">{ld}</script>"datePosted": "{posted}"</html>'


def ctx(**kw):
    base = dict(mode="incremental", known=lambda i, u: False, terms=["data scientist"], max_pages=2,
                stop_after_known=10**9, anchor=0)
    return AdapterContext(**{**base, **kw})


def page(pages, details):
    """pages: {offset: ids}; details: {id: html}. First page arrives by the page's own call."""
    p = FakePage({"https://www.instahyre.com/search-jobs?skills=data%20scientist":
                  [("https://www.instahyre.com/api/v1/job_search?offset=0", listing(pages[0]))]})
    def handler(url, m, h, b):
        if "job_search" in url:
            off = int(url.split("offset=")[1].split("&")[0]); return 200, json.dumps(listing(pages.get(off, [])))
        return 200, details[int(url.split("/job-")[1].split("-")[0])]
    p.fetch_handler = handler; p.url = "https://www.instahyre.com/search-jobs"
    return p


def test_parse_detail_and_listing():
    d = ih.parse_detail(detail_html("2026-09-20"))
    assert d["date"] == date(2026, 9, 20) and d["description"] == "Build models"
    card = ih.parse_list(listing([7]))[0][0]
    j = ih.to_listing(card, d)
    assert (j.source, j.external_id, j.company, j.apply_kind) == ("instahyre", "7", "Acme", "native")
    assert j.posted_date.startswith("2026-09-20") and j.job_url.startswith("https://www.instahyre.com/job-7-")


def test_new_job_fetches_detail_known_and_stale_do_not():
    p = page({0: [30, 20, 10], 20: []}, {30: detail_html("2026-09-25"), 20: detail_html("2026-08-01"), 10: detail_html("2026-09-25")})
    saved, c = [], ctx(known=lambda i, u: i == "30" and False)
    c.save_anchor = saved.append
    with make_session(p) as s:
        out = ih.run(s, c, today=TODAY)
    assert [j.external_id for j in out] == ["30"]           # 20 is stale (>30 days) -> anchor 20 -> 10 skipped unfetched
    assert saved == [20] and c.anchor == 20 and c.stats["skipped_stale"] == 1
    assert not any("/job-10-" in f[0] for f in p.fetches)


def test_known_ids_are_skipped_without_detail_fetch():
    p = page({0: [3, 2], 20: []}, {3: detail_html("2026-09-25")})
    c = ctx(known=lambda i, u: i == "2")
    with make_session(p) as s:
        out = ih.run(s, c, today=TODAY)
    assert [j.external_id for j in out] == ["3"] and c.stats["skipped_known"] == 1


def test_anchor_from_earlier_runs_skips_low_ids():
    p = page({0: [9, 5], 20: []}, {9: detail_html("2026-09-25")})
    with make_session(p) as s:
        out = ih.run(s, ctx(anchor=5), today=TODAY)
    assert [j.external_id for j in out] == ["9"]


def test_second_page_uses_offset_and_cap_returns_partial():
    p = page({0: [4], 20: [3]}, {4: detail_html("2026-09-25"), 3: detail_html("2026-09-25")})
    with make_session(p) as s:
        assert {j.external_id for j in ih.run(s, ctx(), today=TODAY)} == {"4", "3"}
    assert any("offset=20" in f[0] for f in p.fetches)
    p2 = page({0: [4], 20: [3]}, {4: detail_html("2026-09-25"), 3: detail_html("2026-09-25")})
    c = ctx()
    with make_session(p2, max_loads=2) as s:                # goto + 1 fetch, then the cap
        ih.run(s, c, today=TODAY)
    assert c.stats["capped"] is True


def test_missing_description_is_skipped_not_known():
    p = page({0: [4], 20: []}, {4: detail_html("2026-09-25", desc="")})
    c = ctx()
    with make_session(p) as s:
        assert ih.run(s, c, today=TODAY) == []
    assert c.stats["skipped_known"] == 0
```
- [ ] **Step 2:** FAIL. **Step 3: Implement**
```python
"""Instahyre adapter: page 1 of each term arrives by the page's own job_search call; deeper pages and
job details are same-origin fetches. No clicks, never touches Apply/Interested."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from job_dashboard.models import JobListing
from job_dashboard.sources.cdp.types import CapReached, html_to_text

SITE = "instahyre"
HOSTS = ("www.instahyre.com",)
TERMS = ["machine learning engineer", "data scientist", "ai engineer", "llm engineer"]
RETENTION_DAYS = 30
_LD = re.compile(r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', re.S)
_DATE = re.compile(r'"datePosted":\s*"([^"]+)"')


def _list_path(term, offset):
    return (f"/api/v1/job_search?company_size=0&isLandingPage=true&job_type=0&offset={offset}"
            f"&skills={quote(term)}")


def parse_list(body):
    cards = []
    for o in body.get("objects") or []:
        emp = o.get("employer") or {}
        if not o.get("id") or not o.get("title") or not emp.get("company_name"):
            continue
        cards.append(dict(id=int(o["id"]), title=o["title"], company=emp["company_name"],
                          location=o.get("locations"), url=(o.get("public_url") or "").split("?")[0]
                          or f"https://www.instahyre.com/job-{o['id']}-x/"))
    return cards, (body.get("meta") or {}).get("total_count")


def parse_detail(html):
    m = _DATE.search(html or "")
    try:
        posted = date.fromisoformat(m.group(1)[:10]) if m else None
    except ValueError:
        posted = None
    desc = ""
    for blob in _LD.findall(html or ""):
        try:
            j = json.loads(blob)
        except ValueError:
            continue
        if j.get("@type") == "JobPosting":
            desc = html_to_text(j.get("description") or "")
            break
    return {"date": posted, "description": desc}


def to_listing(card, detail) -> JobListing:
    d = detail["date"]
    return JobListing(
        source=SITE, external_id=str(card["id"]), title=card["title"], company=card["company"],
        location=card.get("location"), job_url=card["url"], description=detail["description"],
        posted_date=datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat() if d else None,
        apply_kind="native")


def run(session, ctx, today=None):
    today = today or date.today()
    cutoff = today - timedelta(days=RETENTION_DAYS)
    cands, found = {}, []
    ctx.stats.setdefault("skipped_stale", 0)
    try:
        for term in ctx.terms:
            with session.capture("api/v1/job_search") as cap:
                session.goto(f"https://www.instahyre.com/search-jobs?skills={quote(term)}")
            first = [c for _, b in cap.bodies() for c in parse_list(b)[0]]
            for p in range(1, ctx.max_pages + 1):
                cards = first if p == 1 else parse_list(json.loads(
                    session.fetch(_list_path(term, 20 * (p - 1)), hosts=HOSTS)))[0]
                if not cards:
                    break
                ctx.stats["pages"] += 1
                cands.update({c["id"]: c for c in cards})
        for cid in sorted(cands, reverse=True):
            c = cands[cid]
            if ctx.known(str(cid), c["url"]):
                ctx.stats["skipped_known"] += 1
                continue
            if cid <= ctx.anchor:
                ctx.stats["skipped_stale"] += 1
                continue
            detail = parse_detail(session.fetch(f"/job-{cid}-x/", hosts=HOSTS))
            if detail["date"] and detail["date"] < cutoff:
                ctx.anchor = max(ctx.anchor, cid)
                if ctx.save_anchor:
                    ctx.save_anchor(ctx.anchor)
                continue
            if detail["description"]:
                found.append(to_listing(c, detail))
    except CapReached:
        ctx.stats["capped"] = True
    return found
```
- [ ] **Step 4:** run → PASS (fix real bugs, never loosen assertions). **Step 5: Commit** `git add src/job_dashboard/sources/cdp/instahyre.py tests/test_cdp_instahyre.py`; message `feat(cdp): Instahyre adapter - passive page 1, offset fetch, stale-id anchor`.

---

### Task 4: IIMJobs adapter

**Files:** Create `src/job_dashboard/sources/cdp/iimjobs.py`; Test `tests/test_cdp_iimjobs.py`

**Interfaces:**
- Produces: `SITE = "iimjobs"`, `HOSTS = ("gladiator.iimjobs.com",)`, `TERMS = ["data scientist", "ai engineer", "machine learning engineer", "llm engineer"]`, `POSTING = {24: 1, 72: 3, 168: 7, 720: 30}` (window hours → `posting` days); `parse_search(body) -> (cards, has_more)`; `to_listing(card, description)`; `run(session, ctx)`.
- `run`: `goto("https://www.iimjobs.com/k/data-scientist-jobs")` once (same-origin + cookies), then per term pages `0..max_pages-1` via `fetch("https://gladiator.iimjobs.com/job/search?query=..&page=..&posting=..", headers={"version": "2"})`, stopping a term on `hasMore == False` or empty; ids deduped; known → `skipped_known` (+ `ctx.redate` not used: reposts get a new id); new → `fetch(".../job/detail?jobcode=<id>")` → `data.introText` → `html_to_text`; no text → skip. `hours = 720` in backfill else `ctx.hours`. `CapReached` → `stats["capped"]`.

- [ ] **Step 1: Failing test**
```python
# tests/test_cdp_iimjobs.py
import json
from job_dashboard.sources.cdp import iimjobs as im
from job_dashboard.sources.cdp.types import AdapterContext
from tests.cdp_fakes import FakePage, make_session


def item(i, **kw):
    d = {"id": i, "title": "Data Scientist", "jobdesignation": "Senior Data Scientist", "createdTimeMs": 1790139482397,
         "jobDetailUrl": f"https://www.iimjobs.com/j/acme-data-scientist-{i}", "applyStatus": 1, "applyUrl": "",
         "companyData": {"companyName": "Acme"}, "locations": [{"id": 3, "name": "Bangalore"}, {"id": 4, "name": "Pune"}]}
    d.update(kw); return d


def make(pages, details):
    p = FakePage(); p.url = "https://www.iimjobs.com/k/data-scientist-jobs"
    def handler(url, m, h, b):
        assert h == {"version": "2"} or "detail" in url
        if "/job/search" in url:
            pg = int(url.split("page=")[1].split("&")[0]); items, more = pages.get(pg, ([], False))
            return 200, json.dumps({"data": [item(**i) if isinstance(i, dict) else item(i) for i in items], "hasMore": more})
        return 200, json.dumps({"data": {"introText": details.get(int(url.split("jobcode=")[1]), "")}})
    p.fetch_handler = handler
    return p


def ctx(**kw):
    base = dict(mode="incremental", known=lambda i, u: False, terms=["data scientist"], max_pages=3,
                stop_after_known=10**9, hours=72)
    return AdapterContext(**{**base, **kw})


def test_listing_mapping_native_and_external():
    body = {"data": [item(1), item(2, applyStatus=2, applyUrl="https://acme.com/apply")], "hasMore": False}
    cards, more = im.parse_search(body)
    assert more is False
    n, e = im.to_listing(cards[0], "desc"), im.to_listing(cards[1], "desc")
    assert (n.source, n.external_id, n.company, n.location) == ("iimjobs", "1", "Acme", "Bangalore, Pune")
    assert n.job_url == "https://www.iimjobs.com/j/acme-data-scientist-1" and n.apply_kind == "native"
    assert (e.apply_kind, e.apply_url) == ("external", "https://acme.com/apply")
    assert n.posted_date.startswith("2026-")


def test_walks_pages_until_has_more_false_and_fetches_details_for_new():
    p = make({0: ([1, 2], True), 1: ([3], False)}, {1: "<p>one</p>", 2: "<p>two</p>", 3: "<p>three</p>"})
    c = ctx(known=lambda i, u: i == "2")
    with make_session(p) as s:
        out = im.run(s, c)
    assert [(j.external_id, j.description) for j in out] == [("1", "one"), ("3", "three")]
    assert c.stats["skipped_known"] == 1
    assert not any("jobcode=2" in f[0] for f in p.fetches)
    assert "posting=3" in p.fetches[0][0]


def test_backfill_uses_30_day_posting_and_dedupes_across_terms():
    p = make({0: ([1], False)}, {1: "<p>one</p>"})
    with make_session(p) as s:
        out = im.run(s, ctx(mode="backfill", terms=["a", "b"]))
    assert len(out) == 1 and "posting=30" in p.fetches[0][0]


def test_empty_description_skipped_and_cap_partial():
    p = make({0: ([1], False)}, {1: ""})
    c = ctx()
    with make_session(p) as s:
        assert im.run(s, c) == []
    p2 = make({0: ([1, 2], False)}, {1: "<p>x</p>", 2: "<p>y</p>"})
    c2 = ctx()
    with make_session(p2, max_loads=2) as s:                 # goto + search, cap on first detail
        assert im.run(s, c2) == [] and c2.stats["capped"] is True
```
- [ ] **Step 2:** FAIL. **Step 3: Implement**
```python
"""IIMJobs adapter. The search page is server-rendered and fires no list call, so the list and detail are
same-origin fetches to gladiator.iimjobs.com (header version: 2). Reads only; nothing is clicked."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import quote

from job_dashboard.models import JobListing
from job_dashboard.sources.cdp.types import CapReached, html_to_text

SITE = "iimjobs"
HOSTS = ("gladiator.iimjobs.com",)
API = "https://gladiator.iimjobs.com/job"
TERMS = ["data scientist", "ai engineer", "machine learning engineer", "llm engineer"]
POSTING = {24: 1, 72: 3, 168: 7, 720: 30}
_HDR = {"version": "2"}


def parse_search(body):
    cards = []
    for x in body.get("data") or []:
        company = ((x.get("companyData") or {}).get("companyName") or "").strip()
        if not x.get("id") or not x.get("title") or not company:
            continue
        cards.append(dict(
            id=str(x["id"]), title=x["title"], company=company,
            location=", ".join(l["name"] for l in x.get("locations") or [] if l.get("name")) or None,
            posted_ms=x.get("createdTimeMs"), url=x.get("jobDetailUrl") or f"https://www.iimjobs.com/j/x-{x['id']}",
            apply_url=x.get("applyUrl") or None))
    return cards, bool(body.get("hasMore"))


def to_listing(card, description) -> JobListing:
    ms = card.get("posted_ms")
    return JobListing(
        source=SITE, external_id=card["id"], title=card["title"], company=card["company"],
        location=card.get("location"), job_url=card["url"], description=description,
        posted_date=datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat() if ms else None,
        apply_url=card["apply_url"], apply_kind="external" if card["apply_url"] else "native")


def run(session, ctx):
    hours = 720 if ctx.mode == "backfill" else ctx.hours
    days = POSTING[hours]
    seen, todo, found = set(), [], []
    try:
        session.goto("https://www.iimjobs.com/k/data-scientist-jobs")
        for term in ctx.terms:
            for pg in range(ctx.max_pages):
                body = json.loads(session.fetch(
                    f"{API}/search?query={quote(term)}&page={pg}&posting={days}", hosts=HOSTS, headers=_HDR))
                cards, more = parse_search(body)
                if not cards:
                    break
                ctx.stats["pages"] += 1
                for c in cards:
                    if c["id"] in seen:
                        continue
                    seen.add(c["id"])
                    if ctx.known(c["id"], c["url"]):
                        ctx.stats["skipped_known"] += 1
                    else:
                        todo.append(c)
                if not more:
                    break
        for c in todo:
            data = json.loads(session.fetch(f"{API}/detail?jobcode={c['id']}", hosts=HOSTS, headers=_HDR)).get("data") or {}
            text = html_to_text(data.get("introText") or "")
            if text:
                found.append(to_listing(c, text))
    except CapReached:
        ctx.stats["capped"] = True
    return found
```
- [ ] **Step 4:** PASS. **Step 5: Commit** `feat(cdp): IIMJobs adapter - same-origin search/detail fetch`.

---

### Task 5: Wellfound adapter

**Files:** Create `src/job_dashboard/sources/cdp/wellfound.py`; Test `tests/test_cdp_wellfound.py`

**Interfaces:**
- Produces: `SITE = "wellfound"`, `HOSTS = ("wellfound.com",)`, `INDIA = "1647"`, `TITLES` (8 keyword/title queries), `parse_results(body) -> (jobs, has_next)`; `to_listing(job)`; `run(session, ctx)`.
- `run`: `goto("https://wellfound.com/jobs")` with `capture("graphql")`; find the exchange whose request body `operationName == "JobSearchResultsX"` → template (`headers` restricted to `KEEP`, `operationId`); none → `Blocked("feed request not seen")`. Cutoff = now − (720 h backfill else `ctx.hours`). **Unfiltered walk** (`sortBy=LAST_POSTED`, India tag, `hideOffPlatformJobs=False`, pages `1..ctx.max_pages`) then, for each of `TITLES`, a walk with `customJobTitles=[title]` limited to 3 pages. Every page is a `fetch` POST to `https://wellfound.com/graphql` (the page's own first response is not reused: its sort is not known to be `LAST_POSTED`). A walk stops after 2 consecutive pages with no job at/after the cutoff, or when `hasNextPage` is false. Errors in the graphql body → `Blocked`. Known ids → `skipped_known` and `ctx.redate(id, url, iso(liveStartAt))`; new fresh jobs are listings; ids seen earlier in the run are ignored.

- [ ] **Step 1: Failing test**
```python
# tests/test_cdp_wellfound.py
import json, time
import pytest
from job_dashboard.sources.cdp import wellfound as wf
from job_dashboard.sources.cdp.types import AdapterContext, Blocked
from tests.cdp_fakes import FakePage, FakeRequest, make_session

NOW = time.time()
OP = "tfe/abc"
HDRS = {"x-apollo-signature": "sig", "x-wf-cfp": "cfp", "content-type": "application/json", "cookie": "SECRET"}


def job(i, age_h=1, auto=False, **kw):
    d = {"id": i, "slug": f"role-{i}", "title": "Data Scientist", "description": "<p>Do ML</p>",
         "liveStartAt": NOW - age_h * 3600, "autoPosted": auto, "locationNames": ["Bengaluru"]}
    d.update(kw); return d


def result(jobs, has_next=True, company="Acme"):
    edges = [{"node": {"name": company, "startupId": 1, "slug": "acme", "highlightedJobListings": jobs}}]
    return {"data": {"talent": {"jobSearchResults": {"totalStartupCount": 9, "hasNextPage": has_next,
                                                     "startups": {"edges": edges}}}}}


def feed_page(handler):
    req = FakeRequest("https://wellfound.com/graphql", HDRS, json.dumps(
        {"operationName": "JobSearchResultsX", "variables": {"filterConfigurationInput": {"page": 1}},
         "extensions": {"operationId": OP}}).encode())
    noise = FakeRequest("https://wellfound.com/graphql", HDRS, json.dumps({"operationName": "LastActiveUpdate"}).encode())
    p = FakePage({"https://wellfound.com/jobs": [("https://wellfound.com/graphql", {"data": {}}, noise),
                                                 ("https://wellfound.com/graphql", result([]), req)]})
    p.fetch_handler = handler; p.url = "https://wellfound.com/jobs"
    return p


def ctx(**kw):
    base = dict(mode="incremental", known=lambda i, u: False, terms=[], max_pages=4, stop_after_known=10**9, hours=48)
    return AdapterContext(**{**base, **kw})


def body_of(fetch):
    return json.loads(fetch[3])


def test_parse_results_and_listing():
    jobs, nxt = wf.parse_results(result([job(1), job(2, auto=True)]))
    assert nxt is True and [j["id"] for j in jobs] == ["1", "2"] and jobs[0]["company"] == "Acme"
    n, e = wf.to_listing(jobs[0]), wf.to_listing(jobs[1])
    assert (n.source, n.external_id, n.job_url) == ("wellfound", "1", "https://wellfound.com/jobs/1-role-1")
    assert (n.apply_kind, e.apply_kind, e.apply_url) == ("native", "external", None)
    assert n.description == "Do ML" and n.location == "Bengaluru" and n.posted_date


def test_replays_page_operation_with_captured_headers_only_and_walks_until_stale():
    pages = {1: result([job(1), job(2)]), 2: result([job(3, age_h=200)]), 3: result([job(4, age_h=300)])}
    def handler(url, m, h, b):
        f = json.loads(b)["variables"]["filterConfigurationInput"]
        return 200, json.dumps(pages.get(f["page"], result([], False)) if not f.get("customJobTitles") else result([], False))
    p = feed_page(handler)
    with make_session(p) as s:
        out = wf.run(s, ctx())
    assert [j.external_id for j in out] == ["1", "2"]
    first = p.fetches[0]
    assert first[1] == "POST" and first[0] == "https://wellfound.com/graphql"
    assert first[2]["x-apollo-signature"] == "sig" and first[2]["x-apollo-operation-name"] == "JobSearchResultsX"
    assert "cookie" not in first[2]                                   # only the allowlisted headers are replayed
    f1 = body_of(first)
    assert f1["extensions"]["operationId"] == OP
    fc = f1["variables"]["filterConfigurationInput"]
    assert (fc["page"], fc["sortBy"], fc["hideOffPlatformJobs"], fc["locationTagIds"]) == (1, "LAST_POSTED", False, [wf.INDIA])


def test_title_queries_run_after_the_unfiltered_walk_and_ids_dedupe():
    def handler(url, m, h, b):
        f = json.loads(b)["variables"]["filterConfigurationInput"]
        if f.get("customJobTitles"):
            return 200, json.dumps(result([job(1), job(50)], False))
        return 200, json.dumps(result([job(1)], False))
    p = feed_page(handler)
    with make_session(p) as s:
        out = wf.run(s, ctx())
    assert sorted(j.external_id for j in out) == ["1", "50"]
    titles = [json.loads(f[3])["variables"]["filterConfigurationInput"].get("customJobTitles") for f in p.fetches]
    assert titles[0] is None and [t for t in titles if t] == [[t] for t in wf.TITLES]


def test_known_jobs_skipped_and_redated():
    def handler(url, m, h, b):
        return 200, json.dumps(result([job(1), job(2)], False))
    p = feed_page(handler); bumped = []
    c = ctx(known=lambda i, u: i == "1"); c.redate = lambda i, u, iso: bumped.append(i) or True
    with make_session(p) as s:
        out = wf.run(s, c)
    assert [j.external_id for j in out] == ["2"] and bumped == ["1"] and c.stats["skipped_known"] == 1


def test_no_feed_request_or_graphql_error_is_blocked():
    p = FakePage({"https://wellfound.com/jobs": []}); p.fetch_handler = lambda *a: (200, "{}")
    with make_session(p) as s:
        with pytest.raises(Blocked):
            wf.run(s, ctx())
    p2 = feed_page(lambda u, m, h, b: (200, json.dumps({"errors": [{"message": "PersistedQueryNotFound"}]})))
    with make_session(p2) as s:
        with pytest.raises(Blocked):
            wf.run(s, ctx())


def test_cap_returns_partial():
    p = feed_page(lambda u, m, h, b: (200, json.dumps(result([job(1)], True))))
    c = ctx()
    with make_session(p, max_loads=2) as s:                # goto + one fetch
        out = wf.run(s, c)
    assert c.stats["capped"] is True and [j.external_id for j in out] == ["1"]
```
- [ ] **Step 2:** FAIL. **Step 3: Implement**
```python
"""Wellfound adapter. The /jobs page fires the signed JobSearchResultsX operation once; we learn its header
template and operation id from that exchange (memory only) and replay the same operation, with our own
variables, from inside the tab. Fails closed on any error. Never opens job detail pages."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from job_dashboard.models import JobListing
from job_dashboard.sources.cdp.types import Blocked, CapReached, html_to_text

SITE = "wellfound"
HOSTS = ("wellfound.com",)
INDIA = "1647"
KEEP = {"x-apollo-signature", "x-wf-cfp", "x-angellist-dd-client-referrer-resource",
        "x-requested-with", "apollographql-client-name", "content-type"}
# Wellfound shows <= 3 jobs per startup, so relevant jobs hide behind the cap: also query by title.
TITLES = ["Data Scientist", "Machine Learning Engineer", "AI Engineer", "NLP Engineer",
          "LLM Engineer", "MLOps Engineer", "Applied Scientist", "Data Scientist L1"]
TITLE_PAGES = 3


def parse_results(body):
    res = ((body.get("data") or {}).get("talent") or {}).get("jobSearchResults") or {}
    jobs = []
    for e in (res.get("startups") or {}).get("edges") or []:
        n = e.get("node") or {}
        for x in n.get("highlightedJobListings") or []:
            if x.get("id") and x.get("title") and n.get("name"):
                jobs.append({"id": str(x["id"]), "slug": x.get("slug") or "", "title": x["title"],
                             "company": n["name"], "description": x.get("description") or "",
                             "live": x.get("liveStartAt"), "auto": bool(x.get("autoPosted")),
                             "location": ", ".join(x.get("locationNames") or []) or None})
    return jobs, bool(res.get("hasNextPage"))


def job_url(j) -> str:
    return f"https://wellfound.com/jobs/{j['id']}-{j['slug']}"


def to_listing(j) -> JobListing:
    return JobListing(
        source=SITE, external_id=j["id"], title=j["title"], company=j["company"], location=j["location"],
        job_url=job_url(j), description=html_to_text(j["description"]),
        posted_date=datetime.fromtimestamp(j["live"], timezone.utc).isoformat() if j.get("live") else None,
        apply_kind="external" if j["auto"] else "native")


def _template(session):
    with session.capture("graphql") as cap:
        session.goto("https://wellfound.com/jobs")
    for headers, body, _ in cap.exchanges():
        if isinstance(body, dict) and body.get("operationName") == "JobSearchResultsX":
            return {"headers": {k: v for k, v in headers.items() if k.lower() in KEEP},
                    "op": (body.get("extensions") or {}).get("operationId")}
    raise Blocked("feed request not seen (logged out or challenged)")


def _query(session, tpl, page, title=None):
    f = {"page": page, "equity": {"min": None, "max": None}, "remotePreference": "NO_REMOTE",
         "salary": {"min": None, "max": None}, "yearsExperience": {"min": None, "max": None},
         "sortBy": "LAST_POSTED", "hideOffPlatformJobs": False, "locationTagIds": [INDIA]}
    if title:
        f["customJobTitles"] = [title]
    body = json.dumps({"operationName": "JobSearchResultsX", "variables": {"filterConfigurationInput": f},
                       "extensions": {"operationId": tpl["op"]}})
    headers = dict(tpl["headers"], **{"x-apollo-operation-name": "JobSearchResultsX"})
    data = json.loads(session.fetch("https://wellfound.com/graphql", hosts=HOSTS, method="POST",
                                    headers=headers, body=body))
    if data.get("errors"):
        raise Blocked(f"graphql error: {data['errors'][0].get('message', '?')}")
    return parse_results(data)


def _iso(sec):
    return datetime.fromtimestamp(sec, timezone.utc).isoformat()


def run(session, ctx):
    cutoff = time.time() - (720 if ctx.mode == "backfill" else ctx.hours) * 3600
    seen, found = set(), []

    def walk(tpl, title, max_pages):
        stale = 0
        for pg in range(1, max_pages + 1):
            jobs, has_next = _query(session, tpl, pg, title)
            ctx.stats["pages"] += 1
            fresh = [j for j in jobs if (j["live"] or 0) >= cutoff]
            for j in fresh:
                if j["id"] in seen:
                    continue
                seen.add(j["id"])
                if ctx.known(j["id"], job_url(j)):
                    ctx.stats["skipped_known"] += 1
                    if ctx.redate and ctx.redate(j["id"], job_url(j), _iso(j["live"])):
                        ctx.stats["redated"] = ctx.stats.get("redated", 0) + 1
                else:
                    found.append(to_listing(j))
            stale = 0 if fresh else stale + 1
            if stale >= 2 or not has_next:
                break

    try:
        tpl = _template(session)
        walk(tpl, None, ctx.max_pages)
        for t in TITLES:
            walk(tpl, t, TITLE_PAGES)
    except CapReached:
        ctx.stats["capped"] = True
    return found
```
- [ ] **Step 4:** PASS. **Step 5: Commit** `feat(cdp): Wellfound adapter - replay of the page's own signed operation, title queries`.

---

### Task 6: Register the three adapters + live smokes

**Files:** Modify `runner.py`; Test extend `tests/test_cdp_runner.py`; Create `tests/test_cdp_live_sites.py`

**Interfaces:** `ADAPTERS` gains `wellfound`, `instahyre`, `iimjobs` (each `(module.run, module.TERMS)`; Wellfound's terms list is `[]` because it queries by `TITLES` internally); `WINDOWS["wellfound"] = (24, 48, 168, 720)`, `WINDOWS["iimjobs"] = (24, 72, 168, 720)`, `WINDOWS["instahyre"] = (24, 48, 168, 720)` (unused); `LIMITS_BY_SITE`:
`wellfound {"incremental": (10, 25, 10**9), "backfill": (30, 40, 10**9)}`, `instahyre {"incremental": (3, 30, 10**9), "backfill": (10, 90, 10**9)}`, `iimjobs {"incremental": (5, 40, 10**9), "backfill": (5, 40, 10**9)}`.

- [ ] **Step 1: Failing test**
```python
def test_all_sites_registered_with_limits_windows_and_off_by_default():
    for site in ("wellfound", "instahyre", "iimjobs"):
        assert site in runner.ADAPTERS and site in runner.LIMITS_BY_SITE and site in runner.WINDOWS
    assert runner.LIMITS_BY_SITE["wellfound"]["incremental"][1] == 25
    assert runner.LIMITS_BY_SITE["instahyre"]["backfill"][1] == 90
    assert runner.WINDOWS["iimjobs"] == (24, 72, 168, 720)
    c = conn()                                               # only linkedin switched on by the helper
    _, results = runner.fetch_browser_sources(c, adapters={k: v for k, v in runner.ADAPTERS.items() if k != "linkedin"},
                                              reachable=lambda u: True, session_factory=None)
    assert results == []
```
- [ ] **Step 2–3:** FAIL → implement registrations (import the three modules).
- [ ] **Step 4:** `tests/test_cdp_*.py tests/test_pipeline_browser.py -q` all PASS.
- [ ] **Step 5: Live smokes** — create `tests/test_cdp_live_sites.py` (skipped unless `RUN_CDP_TESTS=1` and Chrome on :9222; each test asserts non-empty listings with title/company/description and prints load counts):
```python
import os
import pytest
from job_dashboard.sources.cdp import iimjobs, instahyre, wellfound
from job_dashboard.sources.cdp.session import CdpSession, cdp_reachable
from job_dashboard.sources.cdp.types import AdapterContext

pytestmark = pytest.mark.skipif(os.environ.get("RUN_CDP_TESTS") != "1" or not cdp_reachable("http://localhost:9222"),
                                reason="needs RUN_CDP_TESTS=1 and Chrome on :9222")


def _run(mod, terms, loads, **kw):
    ctx = AdapterContext("incremental", lambda i, u: False, terms, max_pages=kw.pop("max_pages", 1),
                         stop_after_known=10**9, hours=48, **kw)
    with CdpSession("http://localhost:9222", max_loads=loads) as s:
        jobs = mod.run(s, ctx)
    print(mod.SITE, len(jobs), "jobs; loads", s.loads, "stats", ctx.stats)
    return jobs


def _ok(jobs):
    assert jobs and all(j.title and j.company and j.description and j.job_url for j in jobs)


def test_instahyre():
    _ok(_run(instahyre, ["data scientist"], 6))


def test_iimjobs():
    _ok(_run(iimjobs, ["data scientist"], 6, max_pages=1))


def test_wellfound():
    _ok(_run(wellfound, [], 4, max_pages=2))
```
Run each one at a time: `RUN_CDP_TESTS=1 PYTHONPATH=src python3 -m pytest tests/test_cdp_live_sites.py -q -s -k instahyre` (then iimjobs, wellfound). A `Blocked` means stop and report — do not loop. Payload drift (as happened on LinkedIn) is the expected failure mode: fix the parser and its fixture to the real shape and re-run. Wellfound is the riskiest (signed operation): if the replay returns errors, report the exact message; do not bypass.
- [ ] **Step 6: Commit** `feat(cdp): register Wellfound/Instahyre/IIMJobs; gated live smokes`.

---

## After the plan: gates (not code)

1. Live smokes pass per site; enable one at a time via `PUT /api/agent-settings {"browser_<site>_enabled": true}`; supervised first Refresh each.
2. Wellfound: measure how many hidden jobs the title queries recover; second-day cutoff check against `data/research_baselines/wellfound_2026-09-25.json`.
3. Instahyre: confirm `id > anchor` still tracks date after a few days; set depth from new-job density.
4. IIMJobs stays disabled by default (~27 real roles/week).

## Self-review

- **Spec coverage:** same-origin fetch with host allowlist/cap/non-200 block (T1); anchor in `fetch_state` (T2/T3); Instahyre passive page 1 + offset fetch, detail only for new, id-descending anchor, native apply (T3); IIMJobs `version: 2` fetch, `posting` window, applyStatus mapping, whole window read, disabled default (T4/T2/T6); Wellfound template capture (memory only), LAST_POSTED walk + 8 title queries, cutoff on `liveStartAt`, no detail pages, redate on repost, external for `autoPosted` (T5); limits/windows (T6); switches (T2).
- **Placeholders:** none. Deferred by design: Instahyre `click_pagination` fallback, per-term depth tuning.
- **Type consistency:** `AdapterContext` fields (`anchor`, `save_anchor`, `hours`, `known`, `redate`, `stats`) match Tasks 2-5; `session.fetch(url, *, hosts, method, headers, body) -> str` used identically in Tasks 3-5; `FakePage.fetches` tuples are `(url, method, headers, body)` in all tests; adapters' `run(session, ctx)` signatures match the runner (`Instahyre.run` has an optional `today`).
