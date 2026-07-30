# Company Research Library — Design

## Purpose

Replace "the model auto-picks company facts" with a **curated, per-company
research library**. For a job's company, the system surfaces ~6 candidate
**resources** (a web source: title + URL + short summary). The user picks **1–2**
that fit best; the cover-letter draft grounds only in those picks. Resources and
picks are saved **against the company name** and reused across every job at that
company.

This extends the Cover Letter Engine (`2026-07-26-cover-letter-engine-design.md`)
— it inserts a curation step between research and draft. It does NOT change the
two-sided grounding guarantee or the never-auto-send rule.

Decisions fixed (user-confirmed 2026-07-31):
- **Resource = a source/link** (title, source_url, 1–2 line summary), not an
  atomic fact.
- **Auto-gathered from search** (the existing TinyFish pipeline). No manual URL
  paste in v1.
- **Per company, reused** across all jobs at that company; picks persist.
- **No pick → draft falls back to the top-2 ranked resources** (never blocks).
- **Select at most 2** resources.

## Architecture

New per-company store + a grouping helper; everything else reuses existing
pieces (`company_research`, `draft_cover_letter`, `check_grounding`, the panel).

- `letter/research_store.py` (new): pure logic — turn a `ResearchBundle` into a
  ranked, deduped list of `Resource(source_url, title, summary)` by **grouping
  facts by source_url** (top-ranked facts of a URL joined into its summary),
  capped at ~6. No I/O, no LLM.
- `db.py`: new `company_resources` table + idempotent migration + CRUD, mirroring
  the existing `_ensure_*_table` pattern.
- `api/app.py`: 3 new endpoints + a change to the draft endpoint so it grounds in
  selected resources. `DefaultLetterEngine` gains resource methods.
- `frontend`: `CoverLetterPanel` gains a "Find company research" curation step
  before drafting.

## Data model

`company_resources` table:

| column       | type    | notes                                            |
|--------------|---------|--------------------------------------------------|
| id           | INTEGER | PK autoincrement                                 |
| company_key  | TEXT    | normalized company name (see below)              |
| source_url   | TEXT    | the resource's URL                               |
| title        | TEXT    | source title                                     |
| summary      | TEXT    | 1–2 best fact-sentences from that source (real snippet text) |
| selected     | INTEGER | 0/1 — is this a user pick                         |
| created_at   | TEXT    | ISO timestamp                                     |

Unique on `(company_key, source_url)` — re-running research **upserts** (refreshes
title/summary, preserves `selected`). `company_key` = `company.strip().lower()`
with a trailing `inc/llc/ltd/corp/co` token removed and internal whitespace
collapsed, so "JPMorganChase" and "JPMorgan Chase Inc" map together.

DB CRUD:
- `upsert_company_resources(conn, company_key, resources: list[dict]) -> int`
- `company_resources_for(conn, company_key) -> list[dict]`
- `set_selected_resources(conn, company_key, source_urls: list[str]) -> None`
  (clears prior selection for the company, sets `selected=1` for up to 2 of the
  given urls; ignores urls not in the company's list)
- `selected_resources_for(conn, company_key) -> list[dict]`

## Building resources (`research_store.py`)

`resources_from_bundle(bundle: ResearchBundle) -> list[Resource]`:
- group `bundle.facts` by `source_url`;
- per URL, keep it in the facts' existing ranked order; `title` = derived from the
  first fact/URL (URL host if no title available); `summary` = the top 1–2 fact
  texts for that URL joined with " … ", trimmed to ~240 chars;
- preserve overall ranking (a URL's best fact-rank determines its position);
- cap at `_MAX_RESOURCES = 6`.
- Empty bundle → `[]`.

`Resource` is a small dataclass `(source_url, title, summary)`; the DB layer adds
`selected`.

## API

All under the job (which resolves to its company); resources persist per company.

- `POST /api/jobs/{id}/company-research` → runs `company_research` for the job's
  company, `resources_from_bundle`, upserts them, returns
  `{company, resources:[{source_url,title,summary,selected}]}`. TinyFish down →
  empty list, 200 (never 500). 404 unknown job.
- `GET /api/jobs/{id}/company-resources` → `{company, resources:[...]}` (saved
  list; empty if none gathered yet).
- `POST /api/jobs/{id}/company-resources/select` `{source_urls:[...]}` →
  persists up to 2 picks on the company; returns the updated list. 404 unknown job.
- `POST /api/jobs/{id}/cover-letter/draft` **(changed)**: builds the research
  bundle for the draft from the company's **selected** resources (each selected
  resource → a `Fact(text=summary, source_url=source_url)`). If none selected,
  fall back to the **top-2** of the saved/just-gathered resources. If there are no
  resources at all, behave exactly as today (general grounded pipeline). Response
  shape unchanged (`body, company_facts_used, flags, grounding`).

`DefaultLetterEngine` gains `gather_resources(detail)`, `list_resources(detail)`,
`select_resources(detail, urls)`; `draft` reads selected resources. Injectable in
tests as before (no network/LLM/LaTeX in unit tests).

## UI (`CoverLetterPanel`)

New step before the existing draft flow:
1. **"Find company research"** button → `POST company-research` → renders ~6
   **resource cards**: title, 1–2 line summary, source link (`_blank`,
   `rel=noopener`), and a checkbox.
2. Checking a card calls `select` (max 2; a 3rd check is prevented with a hint).
   Selection state reflects the persisted `selected` flags.
3. **"Draft cover letter"** (existing) then grounds in the picks. A muted line
   notes "using your 2 selected sources" or "no picks — using top 2".
4. Everything else (editable body, amber grounding flags, generate PDF, **no send
   button**) is unchanged. Teal v2 tokens, reduced-motion.

Reused across jobs: opening another JPMorgan role shows the same saved resources
and picks.

## Testing

- `research_store`: grouping by URL, summary join/trim, ranking preserved, cap,
  empty bundle → [] (pure unit tests, no network).
- `db`: upsert refreshes + preserves `selected`; select caps at 2 and clears
  prior; company_key normalization maps variants together; unknown → []; idempotent
  migration. Mirrors `test_cover_letter_db.py`.
- `api`: research/list/select/draft-uses-selected with a fake engine; select cap;
  no-pick fallback to top-2; 404s; TinyFish-down → 200 empty. Real backend shapes.
- `frontend`: cards render with summary + source link + checkbox; max-2 enforced;
  draft uses selection; no send control. Mocked with the exact response shapes.
- One live e2e: real company → gather → pick 2 → draft grounds in exactly those
  two sources (cited) → PDF.
- Existing suite (226 pytest + 37 vitest) stays green.

## Non-goals (deferred)

- Manual "paste a URL" to add a resource (auto-from-search only in v1).
- Editing a resource's summary text in the UI.
- A standalone research-manager page separate from the cover-letter panel.
- Ranking/curation across companies; tagging; expiry/refresh scheduling.
- Auto-send (still the later Application Agent, always per-message confirmed).
