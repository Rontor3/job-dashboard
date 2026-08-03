# Job Industry Categorization — Design

**Date:** 2026-08-02
**Status:** Approved (design), pending spec review
**Depends on:** existing `jobs` table, refresh pipeline, dashboard feed API + frontend

## Goal

Tag every fetched job with two facets — an **Industry** (what the company's
business is) and a **Company-type** (how the company is structured) — computed
**per company, once** (hybrid dictionary + LLM, cached), and surface them in the
dashboard as filterable chips. Lets the candidate browse e.g. "Product companies
in BFSI" instead of a flat 2,358-row list.

## Taxonomy (fixed vocabularies)

**Industry (24):** BFSI · Insurance · Fintech · Consulting & IT Services ·
IT/Software & SaaS · AI/ML & Data Platforms · Healthcare & Pharma ·
Life Sciences & Scientific · Retail & E-commerce · Food, Delivery & Q-commerce ·
Media/Gaming/Entertainment · Telecom · Semiconductors & Hardware ·
Manufacturing & Industrial · Automotive & Mobility · Defense & Aerospace ·
Engineering & Infrastructure · EdTech · Energy & Utilities ·
Travel & Hospitality · Real Estate & PropTech · Consumer & Local Services ·
Public Sector · Other

**Company-type (7):** Product · Services/Consultancy · GCC/Captive · Startup ·
Staffing/Agency · AI Lab/Research · Other  (in-house enterprises such as banks
and manufacturers fall in `Other` — their Industry is the meaningful tag).

Both vocabularies live as module constants (`INDUSTRIES`, `COMPANY_TYPES`); any
value the LLM returns that is not in the list is coerced to `Other`.

## Architecture

Classification is a property of the **company**, not the job, so it is computed
once per distinct company and reused across all that company's jobs and future
refreshes.

Four pieces:

1. `db.py` — new `company_classifications` table + CRUD (kept small; may live in
   a helper module if `db.py` is near the 500-line cap).
2. `classify/company.py` — the hybrid classifier: dictionary first, LLM fallback,
   vocab-constrained. Pure logic, never raises.
3. `scripts/classify_companies.py` (CLI) + a pipeline hook — backfill the
   existing companies and classify new ones on each refresh.
4. API + frontend — feed gains `industry`/`company_type` filters and returns the
   tags; cards show two chips; toolbar gains two dropdowns.

## Data model — `company_classifications`

```sql
CREATE TABLE IF NOT EXISTS company_classifications (
    company_key  TEXT PRIMARY KEY,   -- lower(trim(company))
    industry     TEXT NOT NULL,
    company_type TEXT NOT NULL,
    method       TEXT NOT NULL,      -- 'dict' | 'llm' | 'other'
    updated_at   TEXT NOT NULL
);
```

- Key = `lower(trim(company))` so the dashboard feed can `LEFT JOIN
  company_classifications ON company_classifications.company_key =
  lower(trim(jobs.company))` — no per-job column, and re-classifying updates one
  row.
- CRUD: `upsert_company_classification(conn, company_key, industry, company_type,
  method)`, `get_company_classification(conn, company_key)`,
  `unclassified_companies(conn)` (distinct `lower(trim(company))` on canonical
  jobs with no row here), `distinct_classification_values(conn)` (for populating
  the filter dropdowns).

## Classifier — `classify/company.py`

```python
INDUSTRIES: tuple[str, ...]      # the 25 above
COMPANY_TYPES: tuple[str, ...]   # the 7 above
COMPANY_DICT: dict[str, tuple[str, str]]  # substring-key -> (industry, company_type)

def classify_company(company, sample_title="", sample_desc="", llm=None
                     ) -> tuple[str, str, str]:
    """Return (industry, company_type, method). method ∈ {'dict','llm','other'}.
    Never raises: on any LLM failure returns ('Other','Other','other')."""
```

- **Dictionary first:** `COMPANY_DICT` maps normalized company substrings to exact
  `(industry, company_type)` for the high-frequency names observed in the DB
  (Accenture/Infosys/Capgemini/Deloitte/TCS/Wipro/HCLTech/Cognizant →
  Consulting & IT Services + Services/Consultancy; Barclays/JPMorgan/NatWest/
  Mastercard/Ameriprise → BFSI + Other; NVIDIA → Semiconductors & Hardware +
  Product; Netflix/Reddit → Media + Product; Google/Microsoft/Amazon/Adobe →
  IT/Software & SaaS + Product; Thermo Fisher → Life Sciences & Scientific +
  Product; Mistral/Quantiphi → AI/ML & Data Platforms + AI Lab/Research; …). Match
  by `key in company_key`. First match wins; order longer keys first to avoid
  short-substring false hits.
- **LLM fallback:** unknown → one Ollama call (reuse `letter.draft.make_default_llm`)
  with a prompt listing both vocabularies and the company + sample title/desc,
  asking for exactly `Industry: X` / `Company-type: Y`. Parse; **coerce any
  off-vocab value to `Other`**. Any exception/empty → `('Other','Other','other')`.
- Deterministic and testable: `llm` injectable; dictionary path needs no LLM.

## Where it runs

- `scripts/classify_companies.py` — loads `.env`, opens the DB, calls
  `unclassified_companies`, classifies each (dict→LLM), upserts. Idempotent:
  re-running only touches companies with no row. Prints a summary
  (dict-hits / llm-hits / other).
- **Pipeline hook:** after ingest+dedup in `pipeline.py`, classify any new
  unclassified companies (bounded, incremental). The existing ~1,600-company
  backfill is a **one-time background batch** (one LLM call per non-dictionary
  company — slow); every refresh after is cheap.

## Surfacing — API + frontend

- Feed endpoint accepts optional `industry` and `company_type` query params →
  added to the `WHERE` via the `LEFT JOIN`; each returned job carries `industry`
  and `company_type` (nullable until classified → shown as "Unclassified").
- A `GET /classifications` (or fold into existing meta) returns
  `distinct_classification_values` for the two dropdowns.
- Frontend: two `<select>` filters in the toolbar (Industry, Company-type) wired
  to the feed query; two chips on each job card. Match the existing filter/chip
  styling.

## Error handling

- Classifier never raises; LLM down/unknown → `Other` (job still shows, tagged
  Unclassified/Other, never dropped).
- Unclassified companies (backfill not yet run, or brand-new) → feed shows the
  job with null tags labelled "Unclassified"; filters treat null as excluded only
  when a specific value is selected.
- Off-vocab LLM output coerced to `Other` — the vocab is authoritative.

## Testing

- `classify/company.py`: dictionary hit returns exact tuple + `method='dict'`;
  LLM fallback (fake llm) parses `Industry:/Company-type:` → `method='llm'`;
  off-vocab LLM value coerced to `Other`; llm raising → `('Other','Other','other')`
  and never raises; dictionary longer-key-first (no short-substring false hit).
- DB: `upsert_company_classification` round-trip + updates one row on re-upsert;
  `unclassified_companies` excludes already-classified and duplicates;
  `distinct_classification_values` returns sorted uniques.
- Pipeline/CLI: classifying twice is idempotent (second run classifies zero).
- API: feed with `industry=BFSI` returns only BFSI-company jobs; a job's response
  carries both tags; unclassified job appears with null tags.
- Frontend: a filter selection narrows the feed; chips render (component test or
  smoke per existing frontend test setup).

## Global constraints

- Python 3.11, stdlib `sqlite3`, `pytest`; React + Vite + Vitest for frontend;
  every file under 500 lines.
- Vocabularies are authoritative — never emit a tag outside `INDUSTRIES` /
  `COMPANY_TYPES`; off-vocab → `Other`.
- Classifier never raises; a job is never dropped for being unclassified.
- Classify per company once (cached in `company_classifications`); reuse across
  jobs and refreshes.
- Reuse existing seams: `make_default_llm`, the refresh pipeline, the feed
  query/endpoint, and the existing filter/chip frontend patterns.
