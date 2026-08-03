# Job Industry Categorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tag every job with an Industry + Company-type computed once per company (hybrid dictionary + LLM, cached), filterable in the dashboard.

**Architecture:** New `company_classifications` table (keyed by normalized company), a pure `classify/company.py` classifier (dict → LLM fallback, vocab-constrained, never raises), a CLI + pipeline hook to populate it, feed query + API filters, and two frontend dropdowns + card chips. The feed `LEFT JOIN`s classifications on `lower(trim(company))` — no per-job columns.

**Tech Stack:** Python 3.11, stdlib `sqlite3`, `pytest`, FastAPI; React + Vite + Vitest; Ollama via `letter.draft.make_default_llm`.

## Global Constraints

- Python 3.11; stdlib `sqlite3`; `pytest`; React/Vite/Vitest; every file under 500 lines.
- Two authoritative vocabularies (`INDUSTRIES`, 24; `COMPANY_TYPES`, 7). Never emit a tag outside them — off-vocab → `Other`.
- `classify_company` never raises; on any LLM failure/empty → `("Other","Other","other")`.
- A job is never dropped for being unclassified; null tags render as "Unclassified".
- Classify per company once (cached in `company_classifications`); reuse across jobs/refreshes.
- Company key is `lower(trim(company))` everywhere (CRUD, join, CLI).

---

### Task 1: `company_classifications` table + CRUD

**Files:**
- Modify: `src/job_dashboard/db.py` (add table ensure fn + CRUD; wire into `init_db`)
- Test: `tests/test_company_classifications.py`

**Interfaces:**
- Produces: `_ensure_company_classifications_table(conn)`; `upsert_company_classification(conn, company_key, industry, company_type, method)`; `get_company_classification(conn, company_key)` → dict|None; `unclassified_companies(conn)` → list[str] (distinct `lower(trim(company))` of canonical jobs with no classification row); `distinct_classification_values(conn)` → `{"industries": [...], "company_types": [...]}` (sorted uniques present).

- [ ] **Step 1: Write the failing test**

Create `tests/test_company_classifications.py`:

```python
import sqlite3
from job_dashboard.db import (
    init_db, insert_job, upsert_company_classification,
    get_company_classification, unclassified_companies,
    distinct_classification_values,
)
from job_dashboard.models import JobListing


def _job(company, title="Data Scientist"):
    return JobListing(source="test", external_id=None, title=title, company=company,
                      location="Remote", description="d", job_url=f"http://x/{company}/{title}",
                      job_type=None, is_remote=False, salary_text=None, posted_date=None)


def test_upsert_and_get_roundtrip(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    upsert_company_classification(conn, "acme", "BFSI", "Product", "dict")
    row = get_company_classification(conn, "acme")
    assert row["industry"] == "BFSI" and row["company_type"] == "Product" and row["method"] == "dict"


def test_upsert_updates_single_row(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    upsert_company_classification(conn, "acme", "BFSI", "Product", "dict")
    upsert_company_classification(conn, "acme", "Fintech", "Startup", "llm")
    row = get_company_classification(conn, "acme")
    assert row["industry"] == "Fintech" and row["method"] == "llm"
    assert conn.execute("SELECT COUNT(*) FROM company_classifications").fetchone()[0] == 1


def test_unclassified_companies_excludes_classified_and_dupes(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    insert_job(conn, _job("Acme", "DS"))
    insert_job(conn, _job("Acme", "MLE"))   # same company, different job
    insert_job(conn, _job("Globex", "DS"))
    conn.commit()
    upsert_company_classification(conn, "acme", "BFSI", "Product", "dict")
    got = unclassified_companies(conn)
    assert got == ["globex"]  # acme classified; acme dupe collapsed by key


def test_distinct_values_sorted_uniques(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    upsert_company_classification(conn, "a", "BFSI", "Product", "dict")
    upsert_company_classification(conn, "b", "BFSI", "Startup", "llm")
    vals = distinct_classification_values(conn)
    assert vals["industries"] == ["BFSI"]
    assert vals["company_types"] == ["Product", "Startup"]
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_company_classifications.py -v`
Expected: FAIL (functions not defined).

- [ ] **Step 3: Implement in `db.py`**

Add near the other `_ensure_*` helpers:

```python
def _ensure_company_classifications_table(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS company_classifications (
               company_key  TEXT PRIMARY KEY,
               industry     TEXT NOT NULL,
               company_type TEXT NOT NULL,
               method       TEXT NOT NULL,
               updated_at   TEXT NOT NULL
           )"""
    )


def upsert_company_classification(conn, company_key, industry, company_type, method):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO company_classifications
               (company_key, industry, company_type, method, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(company_key) DO UPDATE SET
               industry=excluded.industry, company_type=excluded.company_type,
               method=excluded.method, updated_at=excluded.updated_at""",
        (company_key, industry, company_type, method, now),
    )
    conn.commit()


def get_company_classification(conn, company_key):
    row = conn.execute(
        "SELECT company_key, industry, company_type, method, updated_at "
        "FROM company_classifications WHERE company_key = ?", (company_key,)).fetchone()
    if row is None:
        return None
    return dict(zip(("company_key", "industry", "company_type", "method", "updated_at"), row))


def unclassified_companies(conn):
    rows = conn.execute(
        """SELECT DISTINCT LOWER(TRIM(j.company)) k
           FROM jobs j
           WHERE j.duplicate_of IS NULL AND j.company IS NOT NULL AND TRIM(j.company) != ''
             AND LOWER(TRIM(j.company)) NOT IN (SELECT company_key FROM company_classifications)
           ORDER BY k""").fetchall()
    return [r[0] for r in rows]


def distinct_classification_values(conn):
    inds = [r[0] for r in conn.execute(
        "SELECT DISTINCT industry FROM company_classifications ORDER BY industry")]
    types = [r[0] for r in conn.execute(
        "SELECT DISTINCT company_type FROM company_classifications ORDER BY company_type")]
    return {"industries": inds, "company_types": types}
```

Wire into `init_db` (after the other ensures, before `conn.commit()`):

```python
    _ensure_company_classifications_table(conn)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_company_classifications.py -v`
Expected: PASS (4).

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/db.py tests/test_company_classifications.py
git commit -m "feat(db): company_classifications table + CRUD"
```

---

### Task 2: Feed query carries + filters by the two tags

**Files:**
- Modify: `src/job_dashboard/db.py` (`query_jobs`, `job_detail`)
- Test: `tests/test_query_jobs_classification.py`

**Interfaces:**
- Consumes: `company_classifications` (Task 1), existing `query_jobs`/`job_detail`.
- Produces: `query_jobs(..., industry=None, company_type=None, ...)` — each returned job dict gains `industry` and `company_type` (None when unclassified); filters narrow by exact tag. `job_detail` also returns both tags. `_JOB_COLUMNS` stays unchanged (extras appended locally).

- [ ] **Step 1: Write the failing test**

Create `tests/test_query_jobs_classification.py`:

```python
from job_dashboard.db import init_db, insert_job, upsert_company_classification, query_jobs
from job_dashboard.models import JobListing


def _job(company, url):
    return JobListing(source="test", external_id=None, title="DS", company=company,
                      location="Remote", description="d", job_url=url, job_type=None,
                      is_remote=False, salary_text=None, posted_date=None)


def _seed(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    insert_job(conn, _job("Acme Bank", "http://x/1"))
    insert_job(conn, _job("Globex", "http://x/2"))
    conn.commit()
    upsert_company_classification(conn, "acme bank", "BFSI", "Product", "dict")
    # Globex left unclassified
    return conn


def test_jobs_carry_tags_and_unclassified_is_none(tmp_path):
    conn = _seed(tmp_path)
    jobs, _ = query_jobs(conn, limit=50)
    by_co = {j["company"]: j for j in jobs}
    assert by_co["Acme Bank"]["industry"] == "BFSI"
    assert by_co["Acme Bank"]["company_type"] == "Product"
    assert by_co["Globex"]["industry"] is None  # unclassified, still present


def test_industry_filter_narrows(tmp_path):
    conn = _seed(tmp_path)
    jobs, total = query_jobs(conn, industry="BFSI", limit=50)
    assert total == 1 and jobs[0]["company"] == "Acme Bank"


def test_company_type_filter_narrows(tmp_path):
    conn = _seed(tmp_path)
    jobs, total = query_jobs(conn, company_type="Product", limit=50)
    assert total == 1 and jobs[0]["company"] == "Acme Bank"
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_query_jobs_classification.py -v`
Expected: FAIL (unexpected `industry` kwarg / missing key).

- [ ] **Step 3: Implement — extend `query_jobs`**

Add params to the signature: `industry=None, company_type=None` (after `source`). In the filter block add:

```python
    if industry:
        where.append("cc.industry = ?")
        params.append(industry)
    if company_type:
        where.append("cc.company_type = ?")
        params.append(company_type)
```

Change the `base` FROM to include the join:

```python
    base = f"""FROM jobs j
               LEFT JOIN match_scores m ON m.job_id = j.id
               LEFT JOIN company_classifications cc
                      ON cc.company_key = LOWER(TRIM(j.company))
               WHERE {' AND '.join(where)}"""
```

Add the two columns to the SELECT (after `m.verdict`) and to the zip:

```python
    rows = conn.execute(
        f"""SELECT j.id, j.title, j.company, j.location, j.job_url, j.job_type,
                   j.is_remote, j.posted_date, j.source, j.status,
                   m.embed_score, m.llm_score, m.verdict,
                   cc.industry, cc.company_type
            {base} ORDER BY {order} LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    return [dict(zip(_JOB_COLUMNS + ("industry", "company_type"), row)) for row in rows], total
```

Extend `job_detail` similarly: add the `LEFT JOIN company_classifications cc ON cc.company_key = LOWER(TRIM(j.company))`, add `cc.industry, cc.company_type` to its SELECT right after `m.verdict`, and change its zip to
`_JOB_COLUMNS + ("industry", "company_type", "description", "strengths", "gaps", "flags")` (keep the SELECT column order matching this tuple).

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_query_jobs_classification.py tests/test_db.py -v`
Expected: PASS (new 3 + existing db tests still green).

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/db.py tests/test_query_jobs_classification.py
git commit -m "feat(db): feed query carries + filters by industry/company_type"
```

---

### Task 3: The hybrid classifier — `classify/company.py`

**Files:**
- Create: `src/job_dashboard/classify/__init__.py` (empty), `src/job_dashboard/classify/company.py`
- Test: `tests/test_classify_company.py`

**Interfaces:**
- Consumes: `letter.draft.make_default_llm` (default llm).
- Produces: `INDUSTRIES: tuple`, `COMPANY_TYPES: tuple`, `COMPANY_DICT: dict`, `classify_company(company, sample_title="", sample_desc="", llm=None) -> (industry, company_type, method)` — never raises.

- [ ] **Step 1: Write the failing test**

Create `tests/test_classify_company.py`:

```python
from job_dashboard.classify import company as cc


def test_dictionary_hit_exact(tmp_path):
    ind, typ, method = cc.classify_company("Accenture Solutions Pvt Ltd", llm=lambda p: "unused")
    assert ind == "Consulting & IT Services" and typ == "Services/Consultancy" and method == "dict"


def test_llm_fallback_parses_vocab(tmp_path):
    def fake(prompt):
        return "Industry: Fintech\nCompany-type: Startup"
    ind, typ, method = cc.classify_company("Zibbra Pay", llm=fake)
    assert ind == "Fintech" and typ == "Startup" and method == "llm"


def test_llm_offvocab_coerced_to_other():
    def fake(prompt):
        return "Industry: Croquet\nCompany-type: Wizardry"
    ind, typ, method = cc.classify_company("Weird Co", llm=fake)
    assert ind == "Other" and typ == "Other" and method == "llm"


def test_llm_raise_is_caught_returns_other():
    def boom(prompt):
        raise RuntimeError("ollama down")
    ind, typ, method = cc.classify_company("Anything", llm=boom)
    assert (ind, typ, method) == ("Other", "Other", "other")


def test_dict_hit_on_compound_name_prefix():
    # "jpmorgan" prefix must still hit inside "JPMorganChase".
    ind, typ, method = cc.classify_company("JPMorganChase", llm=lambda p: "x")
    assert ind == "BFSI" and method == "dict"


def test_short_key_no_midword_false_hit():
    # "ust"/"exl" must NOT match inside unrelated names — those fall through to LLM.
    ind, _, method = cc.classify_company(
        "Reliance Industries Ltd",
        llm=lambda p: "Industry: Energy & Utilities\nCompany-type: Product")
    assert method == "llm" and ind == "Energy & Utilities"  # not dict-matched via "ust"
    # but the real company UST still hits the dictionary
    ind2, _, m2 = cc.classify_company("UST Global", llm=lambda p: "x")
    assert m2 == "dict" and ind2 == "Consulting & IT Services"


def test_non_string_company_never_raises():
    ind, typ, method = cc.classify_company(
        float("nan"), llm=lambda p: "Industry: BFSI\nCompany-type: Product")
    assert isinstance(ind, str) and isinstance(typ, str) and isinstance(method, str)
    assert cc.classify_company(None) == ("Other", "Other", "other")
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_classify_company.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `classify/company.py`**

```python
"""Hybrid per-company classifier: dictionary first, LLM fallback, vocab-constrained.
Never raises — any failure (non-string input, LLM error, off-vocab output)
degrades to Other.
"""
from __future__ import annotations

import re

INDUSTRIES = (
    "BFSI", "Insurance", "Fintech", "Consulting & IT Services",
    "IT/Software & SaaS", "AI/ML & Data Platforms", "Healthcare & Pharma",
    "Life Sciences & Scientific", "Retail & E-commerce",
    "Food, Delivery & Q-commerce", "Media/Gaming/Entertainment", "Telecom",
    "Semiconductors & Hardware", "Manufacturing & Industrial",
    "Automotive & Mobility", "Defense & Aerospace",
    "Engineering & Infrastructure", "EdTech", "Energy & Utilities",
    "Travel & Hospitality", "Real Estate & PropTech",
    "Consumer & Local Services", "Public Sector", "Other",
)
COMPANY_TYPES = (
    "Product", "Services/Consultancy", "GCC/Captive", "Startup",
    "Staffing/Agency", "AI Lab/Research", "Other",
)

# Key (lower) -> (industry, company_type). Matched at a LEADING word boundary
# (`\bkey`), so a prefix like "jpmorgan" still hits "jpmorganchase" but a short
# key like "ust"/"exl" never false-matches mid-word ("industries", "flexlink").
COMPANY_DICT = {
    "tata consultancy": ("Consulting & IT Services", "Services/Consultancy"),
    "accenture": ("Consulting & IT Services", "Services/Consultancy"),
    "capgemini": ("Consulting & IT Services", "Services/Consultancy"),
    "cognizant": ("Consulting & IT Services", "Services/Consultancy"),
    "infosys": ("Consulting & IT Services", "Services/Consultancy"),
    "wipro": ("Consulting & IT Services", "Services/Consultancy"),
    "hcltech": ("Consulting & IT Services", "Services/Consultancy"),
    "deloitte": ("Consulting & IT Services", "Services/Consultancy"),
    "persistent systems": ("IT/Software & SaaS", "Services/Consultancy"),
    "ntt data": ("Consulting & IT Services", "Services/Consultancy"),
    "ust": ("Consulting & IT Services", "Services/Consultancy"),
    "eclerx": ("Consulting & IT Services", "Services/Consultancy"),
    "exl": ("Consulting & IT Services", "Services/Consultancy"),
    "quantiphi": ("AI/ML & Data Platforms", "AI Lab/Research"),
    "mistral": ("AI/ML & Data Platforms", "AI Lab/Research"),
    "jpmorgan": ("BFSI", "Other"),
    "barclays": ("BFSI", "Other"),
    "natwest": ("BFSI", "Other"),
    "mastercard": ("BFSI", "Product"),
    "ameriprise": ("BFSI", "Other"),
    "nvidia": ("Semiconductors & Hardware", "Product"),
    "netflix": ("Media/Gaming/Entertainment", "Product"),
    "reddit": ("Media/Gaming/Entertainment", "Product"),
    "thermo fisher": ("Life Sciences & Scientific", "Product"),
    "husky injection": ("Manufacturing & Industrial", "Product"),
    "general dynamics": ("Defense & Aerospace", "Services/Consultancy"),
    "walmart": ("Retail & E-commerce", "Product"),
    "amazon": ("Retail & E-commerce", "Product"),
    "google": ("IT/Software & SaaS", "Product"),
    "microsoft": ("IT/Software & SaaS", "Product"),
    "adobe": ("IT/Software & SaaS", "Product"),
    "humana": ("Healthcare & Pharma", "Product"),
    "talabat": ("Food, Delivery & Q-commerce", "Product"),
}

_LLM_PROMPT = (
    "Classify the company into EXACTLY one Industry and one Company-type from "
    "the allowed lists. Reply with two lines and nothing else:\n"
    "Industry: <one of the industries>\nCompany-type: <one of the types>\n\n"
    "Industries: {industries}\nCompany-types: {types}\n\n"
    "Company: {company}\nExample role: {title}\nContext: {desc}\n"
)


def _dict_lookup(company_key):
    for key, pair in COMPANY_DICT.items():
        # Leading word boundary: matches "ust" in "ust global" but not in
        # "industries"; matches the "jpmorgan" prefix of "jpmorganchase".
        if re.search(r"\b" + re.escape(key), company_key):
            return pair
    return None


def _parse_llm(text):
    industry, ctype = "Other", "Other"
    for line in (text or "").splitlines():
        low = line.lower()
        if low.startswith("industry:"):
            industry = line.split(":", 1)[1].strip()
        elif low.startswith("company-type:") or low.startswith("company type:"):
            ctype = line.split(":", 1)[1].strip()
    industry = industry if industry in INDUSTRIES else "Other"
    ctype = ctype if ctype in COMPANY_TYPES else "Other"
    return industry, ctype


def classify_company(company, sample_title="", sample_desc="", llm=None):
    # Whole body guarded: non-string input, dict-lookup, and the LLM branch all
    # degrade to Other rather than raising.
    try:
        key = str(company or "").strip().lower()
        if not key:
            return ("Other", "Other", "other")
        hit = _dict_lookup(key)
        if hit:
            return (hit[0], hit[1], "dict")
        if llm is None:
            from job_dashboard.letter.draft import make_default_llm
            llm = make_default_llm()
        prompt = _LLM_PROMPT.format(
            industries=", ".join(INDUSTRIES), types=", ".join(COMPANY_TYPES),
            company=str(company), title=str(sample_title or "")[:120],
            desc=str(sample_desc or "")[:400])
        out = llm(prompt)
        industry, ctype = _parse_llm(out if isinstance(out, str) else "")
        return (industry, ctype, "llm")
    except Exception:
        return ("Other", "Other", "other")
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_classify_company.py -v`
Expected: PASS (7).

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/classify/ tests/test_classify_company.py
git commit -m "feat(classify): hybrid per-company industry/type classifier"
```

---

### Task 4: Backfill CLI + pipeline hook

**Files:**
- Create: `src/job_dashboard/classify/run.py` (batch fn), `scripts/classify_companies.py` (CLI)
- Modify: `src/job_dashboard/pipeline.py` (classify new companies after dedup)
- Test: `tests/test_classify_run.py`

**Interfaces:**
- Consumes: `unclassified_companies`, `upsert_company_classification`, `classify_company`, and a per-company sample (any one job's title/description).
- Produces: `classify_unclassified(conn, llm=None, limit=None) -> dict` (counts by method) — idempotent (only unclassified companies).

- [ ] **Step 1: Write the failing test**

Create `tests/test_classify_run.py`:

```python
from job_dashboard.db import init_db, insert_job, get_company_classification
from job_dashboard.classify.run import classify_unclassified
from job_dashboard.models import JobListing


def _job(company, url, title="DS", desc="d"):
    return JobListing(source="test", external_id=None, title=title, company=company,
                      location="Remote", description=desc, job_url=url, job_type=None,
                      is_remote=False, salary_text=None, posted_date=None)


def test_classifies_all_and_is_idempotent(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    insert_job(conn, _job("Accenture", "http://x/1"))     # dict hit
    insert_job(conn, _job("Zzz Labs", "http://x/2"))       # llm fallback
    conn.commit()
    fake = lambda p: "Industry: AI/ML & Data Platforms\nCompany-type: Startup"
    r1 = classify_unclassified(conn, llm=fake)
    assert r1["dict"] == 1 and r1["llm"] == 1
    assert get_company_classification(conn, "accenture")["industry"] == "Consulting & IT Services"
    assert get_company_classification(conn, "zzz labs")["company_type"] == "Startup"
    # second run: nothing left to classify
    r2 = classify_unclassified(conn, llm=fake)
    assert r2["dict"] == 0 and r2["llm"] == 0 and r2["total"] == 0
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_classify_run.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `classify/run.py`**

```python
"""Batch: classify every not-yet-classified company. Idempotent."""
from job_dashboard.db import (
    unclassified_companies, upsert_company_classification, get_sample_job_for_company,
)
from job_dashboard.classify.company import classify_company


def classify_unclassified(conn, llm=None, limit=None):
    keys = unclassified_companies(conn)
    if limit is not None:
        keys = keys[:limit]
    counts = {"dict": 0, "llm": 0, "other": 0, "total": 0}
    for key in keys:
        title, desc, display = get_sample_job_for_company(conn, key)
        industry, ctype, method = classify_company(display or key, title, desc, llm=llm)
        upsert_company_classification(conn, key, industry, ctype, method)
        counts[method] = counts.get(method, 0) + 1
        counts["total"] += 1
    return counts
```

Add `get_sample_job_for_company` to `db.py`:

```python
def get_sample_job_for_company(conn, company_key):
    """One representative (title, description, display_company) for a company key."""
    row = conn.execute(
        """SELECT title, description, company FROM jobs
           WHERE LOWER(TRIM(company)) = ? AND duplicate_of IS NULL
           ORDER BY id LIMIT 1""", (company_key,)).fetchone()
    return (row[0], row[1], row[2]) if row else ("", "", company_key)
```

Create `scripts/classify_companies.py`:

```python
"""Backfill/refresh company industry + type classifications.

    python3 scripts/classify_companies.py [--limit N]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    from job_dashboard.env import load_env_file
    load_env_file()
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--db", default="data/jobs.db")
    args = ap.parse_args()
    from job_dashboard.db import init_db
    from job_dashboard.classify.run import classify_unclassified
    conn = init_db(args.db)
    counts = classify_unclassified(conn, limit=args.limit)
    print(f"classified {counts['total']} companies "
          f"(dict={counts['dict']}, llm={counts['llm']}, other={counts['other']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Hook into `pipeline.py` after dedup (bounded, best-effort — never aborts the refresh):

```python
    classified = 0
    try:
        from job_dashboard.classify.run import classify_unclassified
        classified = classify_unclassified(conn).get("total", 0)
    except Exception:
        classified = 0
```

Add `"companies_classified": classified` to the returned dict.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_classify_run.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/classify/run.py scripts/classify_companies.py src/job_dashboard/db.py src/job_dashboard/pipeline.py tests/test_classify_run.py
git commit -m "feat(classify): backfill CLI + pipeline hook (idempotent)"
```

---

### Task 5: API — feed filters + dropdown values

**Files:**
- Modify: `src/job_dashboard/api/app.py`
- Test: `tests/test_api_classification.py`

**Interfaces:**
- Produces: `GET /api/jobs` gains `industry` and `company_type` query params (passed to `query_jobs`); `GET /api/classifications` returns `distinct_classification_values`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_classification.py`:

```python
from fastapi.testclient import TestClient
from job_dashboard.api.app import create_app
from job_dashboard.db import init_db, insert_job, upsert_company_classification
from job_dashboard.models import JobListing


def _job(company, url):
    return JobListing(source="test", external_id=None, title="DS", company=company,
                      location="Remote", description="d", job_url=url, job_type=None,
                      is_remote=False, salary_text=None, posted_date=None)


def _app(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    insert_job(conn, _job("Acme Bank", "http://x/1"))
    insert_job(conn, _job("Globex", "http://x/2"))
    conn.commit()
    upsert_company_classification(conn, "acme bank", "BFSI", "Product", "dict")
    conn.close()
    return TestClient(create_app(db_path=db))


def test_feed_filters_by_industry(tmp_path):
    client = _app(tmp_path)
    r = client.get("/api/jobs?industry=BFSI")
    body = r.json()
    assert body["total"] == 1 and body["jobs"][0]["company"] == "Acme Bank"
    assert body["jobs"][0]["industry"] == "BFSI"


def test_classifications_endpoint(tmp_path):
    client = _app(tmp_path)
    r = client.get("/api/classifications")
    assert r.json() == {"industries": ["BFSI"], "company_types": ["Product"]}
```

(If `create_app` uses a different db-injection param, match the existing test setup in `tests/` — check `test_api*.py`.)

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_api_classification.py -v`
Expected: FAIL (params/endpoint missing).

- [ ] **Step 3: Implement in `app.py`**

Add `industry: str = None, company_type: str = None` to the `list_jobs` signature and pass them through to `query_jobs(... industry=industry, company_type=company_type ...)`. Add the endpoint:

```python
    @app.get("/api/classifications")
    def classifications():
        from job_dashboard.db import distinct_classification_values
        with db() as conn:
            return distinct_classification_values(conn)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_api_classification.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/api/app.py tests/test_api_classification.py
git commit -m "feat(api): feed industry/company_type filters + /api/classifications"
```

---

### Task 6: Frontend — two filter dropdowns + card chips

**Files:**
- Modify: `frontend/src/App.jsx` (FilterBar: two `<select>`; fetch classification values), `frontend/src/components/Feed.jsx` (two chips per card)
- Test: extend the existing frontend test setup (Vitest) if present; otherwise a build/smoke check.

**Interfaces:**
- Consumes: `GET /api/classifications`, `GET /api/jobs?industry=&company_type=`, job objects now carrying `industry`/`company_type`.

- [ ] **Step 1: Read the existing patterns**

Read `frontend/src/App.jsx` (the `FilterBar` component + the `source`/`sort` `<select>` pattern and how `filters` state maps to the `/api/jobs` query string) and `frontend/src/components/Feed.jsx` (how a job card renders badges, e.g. `ScoreBadge`). Mirror these exactly.

- [ ] **Step 2: Add the two dropdowns to FilterBar**

- On mount, `fetch('/api/classifications')` → store `{industries, company_types}`.
- Add two `<select>` controls beside the existing Source dropdown: **Industry** (options: "All industries" + each industry) and **Company-type** ("All types" + each type), following the exact markup/handler pattern of the Source select. Selecting sets `filters.industry` / `filters.company_type`.
- Ensure the `/api/jobs` fetch appends `industry`/`company_type` when set (mirror how `source` is appended in the existing query-string builder).

- [ ] **Step 3: Add chips to the job card**

In `Feed.jsx`, where the card renders company/source, render two small chips when present: `job.industry` and `job.company_type` (skip when null; show a muted "Unclassified" only for industry when both are null). Reuse the existing chip/badge styling.

- [ ] **Step 4: Verify**

Run the frontend test/build the project uses (`npm --prefix frontend test` or `npm --prefix frontend run build`). Expected: passes/builds. Then a manual preview check happens in the live e2e.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.jsx frontend/src/components/Feed.jsx
git commit -m "feat(ui): industry + company-type filters and card chips"
```

---

## Self-Review

- **Spec coverage:** table + CRUD (T1); feed carries+filters (T2); hybrid classifier w/ vocab coercion + never-raise (T3); backfill CLI + pipeline hook + idempotency (T4); API filters + dropdown values (T5); frontend dropdowns + chips (T6). All spec sections mapped.
- **Placeholder scan:** none — every backend step has real code; the frontend task points at the exact files/patterns to mirror (justified: it must match existing unseen component markup).
- **Type consistency:** `classify_company` returns `(industry, company_type, method)` used consistently by `classify_unclassified` and the CLI; `company_key = LOWER(TRIM(company))` is identical in CRUD, the feed/detail joins, `unclassified_companies`, and `get_sample_job_for_company`; `_JOB_COLUMNS` left unchanged with extras appended locally in both `query_jobs` and `job_detail`.
- **Known integration point:** T5 Step 1 notes the `create_app` db-injection must match the existing API tests — the implementer verifies against `tests/test_api*.py` rather than assuming.
