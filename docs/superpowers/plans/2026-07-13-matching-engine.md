# Matching Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score every aggregated job against Rakshit's profile (local embeddings for all + Claude-agent deep-rank for the top slice), with cross-source duplicates marked — never deleted — under a "suspected duplicates" listing.

**Architecture:** `pipeline.run_pipeline()` chains the existing `run_ingest` with three new stages: `match/dedup.py` marks cross-source duplicates via normalized company+title keys; `match/profile_text.py` composes and hashes the profile text; `match/embedder.py` cosine-scores every canonical job with sentence-transformers (injectable model). A `rank_io` CLI + `.claude/commands/rank.md` let Claude Code subagents deep-rank the top N and write results back through `db.py` — which remains the only module touching SQL.

**Tech Stack:** Python 3.11+, sqlite3 (stdlib), sentence-transformers (lazy import), pytest.

## Global Constraints

- Scores are **filters, never gates**: no stage removes or hides a listing; all jobs stay queryable.
- Suspected duplicates are **marked (`duplicate_of`), never deleted**; any listing output shows them under their own "suspected duplicates" section annotated with the canonical job. Deletion happens only on an explicit later user command (out of scope here).
- `db.py` is the only module that touches SQL.
- No test performs a real network call or requires the sentence-transformers download — the embedding model is injected; tests use a fake.
- Scoring runs only on canonical rows (`duplicate_of IS NULL`).
- Profile text is composed from `01-candidate-profile.md` + the career-goals block of `04-job-evaluation.md`, SHA-256 hashed; rows whose stored `profile_hash` differs from the current hash are stale and get re-scored (and their LLM fields reset).
- LLM evaluation validates: `llm_score` int 0–100; `verdict` ∈ {Strong Fit, Good Fit, Moderate Fit, Weak Fit, Poor Fit}; writing an LLM evaluation for a job with no embed score is an error.
- The evaluation rubric lives in `04-job-evaluation.md` — never hard-coded in Python.

---

## File Structure

```
src/job_dashboard/
  db.py                     # MODIFIED: match_scores table, duplicate_of column, score fns
  pipeline.py               # NEW: run_pipeline() orchestration
  rank_io.py                # NEW: CLI bridge for the /rank Claude command
  match/
    __init__.py             # NEW (empty)
    profile_text.py         # NEW: compose_profile_text() -> ProfileText(text, hash)
    dedup.py                # NEW: normalized_key(), mark_duplicates()
    embedder.py             # NEW: cosine(), compute_embed_scores(), load_default_model()
.claude/commands/rank.md    # NEW: /rank deep-rank command for Claude Code
requirements.txt            # MODIFIED: + sentence-transformers
tests/
  test_db_match.py          # NEW
  test_profile_text.py      # NEW
  test_dedup.py             # NEW
  test_embedder.py          # NEW
  test_pipeline.py          # NEW
  test_rank_io.py           # NEW
```

---

### Task 1: DB extensions — `match_scores` table, `duplicate_of` column, score functions

**Files:**
- Modify: `src/job_dashboard/db.py`
- Test: `tests/test_db_match.py`

**Interfaces:**
- Consumes: existing `init_db(path)`, `insert_job(conn, job)` from `job_dashboard.db`.
- Produces (all in `job_dashboard.db`, used by Tasks 3–6):
  - `upsert_embed_score(conn, job_id: int, embed_score: float, profile_hash: str) -> None` (re-upsert resets LLM fields)
  - `jobs_needing_embed_score(conn, profile_hash: str) -> list[tuple[int, str]]` — (id, description) of canonical jobs with no score or a stale hash
  - `record_llm_evaluation(conn, job_id: int, llm_score: int, verdict: str, strengths: list, gaps: list, flags: dict) -> None`
  - `top_unranked_jobs(conn, limit: int = 30) -> list[dict]` — keys: id, title, company, location, job_url, description, embed_score
  - `canonical_jobs_for_dedup(conn) -> list[tuple]` — (id, company, title, fetched_at, source), ordered by (fetched_at, id)
  - `mark_duplicate(conn, job_id: int, canonical_id: int) -> None`
  - `suspected_duplicates(conn) -> list[dict]` — keys: id, title, company, source, job_url, duplicate_of, canonical_source

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_db_match.py
import pytest

from job_dashboard.db import (
    canonical_jobs_for_dedup, init_db, insert_job, jobs_needing_embed_score,
    mark_duplicate, record_llm_evaluation, suspected_duplicates,
    top_unranked_jobs, upsert_embed_score,
)
from job_dashboard.models import JobListing


def _job(n, **overrides):
    fields = dict(
        source=f"src{n}", title=f"Role {n}", company=f"Co {n}",
        job_url=f"https://example.com/{n}", description=f"desc {n}",
    )
    fields.update(overrides)
    return JobListing(**fields)


def test_upsert_embed_score_then_needing_list_shrinks(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job(1))
    job_id = conn.execute("SELECT id FROM jobs").fetchone()[0]

    assert jobs_needing_embed_score(conn, "hashA") == [(job_id, "desc 1")]
    upsert_embed_score(conn, job_id, 0.82, "hashA")
    assert jobs_needing_embed_score(conn, "hashA") == []


def test_stale_profile_hash_marks_job_as_needing_rescore(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job(1))
    job_id = conn.execute("SELECT id FROM jobs").fetchone()[0]
    upsert_embed_score(conn, job_id, 0.82, "hashA")

    assert jobs_needing_embed_score(conn, "hashB") == [(job_id, "desc 1")]


def test_reupsert_resets_llm_fields(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job(1))
    job_id = conn.execute("SELECT id FROM jobs").fetchone()[0]
    upsert_embed_score(conn, job_id, 0.82, "hashA")
    record_llm_evaluation(conn, job_id, 74, "Good Fit", ["s"], ["g"], {})

    upsert_embed_score(conn, job_id, 0.5, "hashB")

    row = conn.execute(
        "SELECT llm_score, verdict FROM match_scores WHERE job_id = ?", (job_id,)
    ).fetchone()
    assert row == (None, None)


def test_record_llm_evaluation_validates_inputs(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job(1))
    job_id = conn.execute("SELECT id FROM jobs").fetchone()[0]

    with pytest.raises(ValueError):  # no embed score yet
        record_llm_evaluation(conn, job_id, 74, "Good Fit", [], [], {})

    upsert_embed_score(conn, job_id, 0.8, "h")
    with pytest.raises(ValueError):
        record_llm_evaluation(conn, job_id, 101, "Good Fit", [], [], {})
    with pytest.raises(ValueError):
        record_llm_evaluation(conn, job_id, 74, "Amazing Fit", [], [], {})


def test_top_unranked_orders_by_embed_score_and_skips_duplicates_and_ranked(tmp_path):
    conn = init_db(tmp_path / "t.db")
    for n in (1, 2, 3, 4):
        insert_job(conn, _job(n))
    ids = [r[0] for r in conn.execute("SELECT id FROM jobs ORDER BY id").fetchall()]
    upsert_embed_score(conn, ids[0], 0.9, "h")
    upsert_embed_score(conn, ids[1], 0.7, "h")
    upsert_embed_score(conn, ids[2], 0.95, "h")
    upsert_embed_score(conn, ids[3], 0.99, "h")
    record_llm_evaluation(conn, ids[0], 80, "Strong Fit", [], [], {})  # already ranked
    mark_duplicate(conn, ids[3], ids[2])                               # duplicate

    top = top_unranked_jobs(conn, limit=10)

    assert [j["id"] for j in top] == [ids[2], ids[1]]
    assert top[0]["embed_score"] == 0.95


def test_mark_and_list_suspected_duplicates(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job(1, source="jobspy:linkedin"))
    insert_job(conn, _job(2, source="remoteok"))
    ids = [r[0] for r in conn.execute("SELECT id FROM jobs ORDER BY id").fetchall()]

    mark_duplicate(conn, ids[1], ids[0])
    dupes = suspected_duplicates(conn)

    assert len(dupes) == 1
    assert dupes[0]["id"] == ids[1]
    assert dupes[0]["duplicate_of"] == ids[0]
    assert dupes[0]["canonical_source"] == "jobspy:linkedin"


def test_canonical_jobs_for_dedup_excludes_marked_rows(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job(1))
    insert_job(conn, _job(2))
    ids = [r[0] for r in conn.execute("SELECT id FROM jobs ORDER BY id").fetchall()]
    mark_duplicate(conn, ids[1], ids[0])

    rows = canonical_jobs_for_dedup(conn)
    assert [r[0] for r in rows] == [ids[0]]


def test_init_db_upgrades_existing_database_in_place(tmp_path):
    # simulate a pre-matching database: create it, then re-open via init_db
    path = tmp_path / "t.db"
    conn = init_db(path)
    insert_job(conn, _job(1))
    conn.close()

    conn2 = init_db(path)  # must not fail on existing duplicate_of / match_scores
    cols = [r[1] for r in conn2.execute("PRAGMA table_info(jobs)").fetchall()]
    assert "duplicate_of" in cols
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_db_match.py -v`
Expected: FAIL with `ImportError` (new names don't exist in `job_dashboard.db`)

- [ ] **Step 3: Implement the db extensions**

Add to `src/job_dashboard/db.py` — `import json` at the top, then after the existing `SCHEMA`:

```python
MATCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS match_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL UNIQUE,
    embed_score REAL NOT NULL,
    profile_hash TEXT NOT NULL,
    llm_score INTEGER,
    verdict TEXT,
    strengths TEXT,
    gaps TEXT,
    flags TEXT,
    scored_at TEXT NOT NULL,
    llm_scored_at TEXT
);
"""

VALID_VERDICTS = {"Strong Fit", "Good Fit", "Moderate Fit", "Weak Fit", "Poor Fit"}
```

Extend `init_db` (replace its body):

```python
def init_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executescript(MATCH_SCHEMA)
    _ensure_duplicate_of_column(conn)
    conn.commit()
    return conn


def _ensure_duplicate_of_column(conn):
    cols = [row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()]
    if "duplicate_of" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN duplicate_of INTEGER")
```

Append the score/dedup functions:

```python
def upsert_embed_score(conn, job_id, embed_score, profile_hash):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO match_scores (job_id, embed_score, profile_hash, scored_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(job_id) DO UPDATE SET
             embed_score = excluded.embed_score,
             profile_hash = excluded.profile_hash,
             scored_at = excluded.scored_at,
             llm_score = NULL, verdict = NULL, strengths = NULL,
             gaps = NULL, flags = NULL, llm_scored_at = NULL""",
        (job_id, embed_score, profile_hash, now),
    )
    conn.commit()


def jobs_needing_embed_score(conn, profile_hash):
    return conn.execute(
        """SELECT j.id, j.description FROM jobs j
           LEFT JOIN match_scores m ON m.job_id = j.id
           WHERE j.duplicate_of IS NULL
             AND (m.job_id IS NULL OR m.profile_hash != ?)
           ORDER BY j.id""",
        (profile_hash,),
    ).fetchall()


def record_llm_evaluation(conn, job_id, llm_score, verdict, strengths, gaps, flags):
    if not isinstance(llm_score, int) or not 0 <= llm_score <= 100:
        raise ValueError(f"llm_score must be an int 0-100, got {llm_score!r}")
    if verdict not in VALID_VERDICTS:
        raise ValueError(f"verdict must be one of {sorted(VALID_VERDICTS)}, got {verdict!r}")
    existing = conn.execute(
        "SELECT 1 FROM match_scores WHERE job_id = ?", (job_id,)
    ).fetchone()
    if existing is None:
        raise ValueError(f"job {job_id} has no embed score yet; run the pipeline first")
    conn.execute(
        """UPDATE match_scores
           SET llm_score = ?, verdict = ?, strengths = ?, gaps = ?, flags = ?,
               llm_scored_at = ?
           WHERE job_id = ?""",
        (llm_score, verdict, json.dumps(strengths), json.dumps(gaps),
         json.dumps(flags), datetime.now(timezone.utc).isoformat(), job_id),
    )
    conn.commit()


def top_unranked_jobs(conn, limit=30):
    rows = conn.execute(
        """SELECT j.id, j.title, j.company, j.location, j.job_url, j.description,
                  m.embed_score
           FROM jobs j JOIN match_scores m ON m.job_id = j.id
           WHERE j.duplicate_of IS NULL AND m.llm_score IS NULL
           ORDER BY m.embed_score DESC, j.id
           LIMIT ?""",
        (limit,),
    ).fetchall()
    keys = ("id", "title", "company", "location", "job_url", "description", "embed_score")
    return [dict(zip(keys, row)) for row in rows]


def canonical_jobs_for_dedup(conn):
    return conn.execute(
        """SELECT id, company, title, fetched_at, source FROM jobs
           WHERE duplicate_of IS NULL
           ORDER BY fetched_at, id"""
    ).fetchall()


def mark_duplicate(conn, job_id, canonical_id):
    conn.execute("UPDATE jobs SET duplicate_of = ? WHERE id = ?", (canonical_id, job_id))
    conn.commit()


def suspected_duplicates(conn):
    rows = conn.execute(
        """SELECT d.id, d.title, d.company, d.source, d.job_url, d.duplicate_of,
                  c.source
           FROM jobs d JOIN jobs c ON c.id = d.duplicate_of
           WHERE d.duplicate_of IS NOT NULL
           ORDER BY d.id"""
    ).fetchall()
    keys = ("id", "title", "company", "source", "job_url", "duplicate_of",
            "canonical_source")
    return [dict(zip(keys, row)) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_db_match.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Run the whole suite to confirm nothing broke**

Run: `python3 -m pytest`
Expected: all pass (20 existing + 8 new)

- [ ] **Step 6: Commit**

```bash
git add src/job_dashboard/db.py tests/test_db_match.py
git commit -m "feat: add match_scores table, duplicate_of column, and score functions"
```

---

### Task 2: `match/profile_text.py` — compose + hash the profile text

**Files:**
- Create: `src/job_dashboard/match/__init__.py` (empty)
- Create: `src/job_dashboard/match/profile_text.py`
- Test: `tests/test_profile_text.py`

**Interfaces:**
- Produces: `compose_profile_text(profile_file=PROFILE_FILE, evaluation_file=EVALUATION_FILE) -> ProfileText` where `ProfileText` is a dataclass with `.text: str` and `.hash: str` (SHA-256 hex). Module constants `PROFILE_FILE` and `EVALUATION_FILE` point at the real vendored profile paths. Raises `FileNotFoundError` with an actionable message if the profile file is missing.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_profile_text.py
import pytest

from job_dashboard.match.profile_text import compose_profile_text

PROFILE_MD = """# Candidate Profile
## Technical Skills
- Python, ML
"""

EVAL_MD = """# Job Evaluation Framework
**Career goals:**
- Move into AI Engineer roles.
- Remote-first.

**Motivation filter:** ...
"""


def test_compose_includes_profile_and_career_goals(tmp_path):
    profile = tmp_path / "01.md"
    evaluation = tmp_path / "04.md"
    profile.write_text(PROFILE_MD)
    evaluation.write_text(EVAL_MD)

    result = compose_profile_text(profile, evaluation)

    assert "Python, ML" in result.text
    assert "Move into AI Engineer roles." in result.text
    assert "Motivation filter" not in result.text  # only the goals block, not the rubric
    assert len(result.hash) == 64


def test_hash_changes_when_profile_changes(tmp_path):
    profile = tmp_path / "01.md"
    evaluation = tmp_path / "04.md"
    profile.write_text(PROFILE_MD)
    evaluation.write_text(EVAL_MD)
    first = compose_profile_text(profile, evaluation)

    profile.write_text(PROFILE_MD + "- FastAPI\n")
    second = compose_profile_text(profile, evaluation)

    assert first.hash != second.hash


def test_missing_profile_raises_actionable_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="/setup"):
        compose_profile_text(tmp_path / "nope.md", tmp_path / "also-nope.md")


def test_missing_evaluation_file_is_tolerated(tmp_path):
    profile = tmp_path / "01.md"
    profile.write_text(PROFILE_MD)

    result = compose_profile_text(profile, tmp_path / "absent.md")
    assert "Python, ML" in result.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_profile_text.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'job_dashboard.match'`

- [ ] **Step 3: Implement**

```bash
touch "src/job_dashboard/match/__init__.py"
```

```python
# src/job_dashboard/match/profile_text.py
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

PROFILE_FILE = Path(
    ".claude/skills/ai-job-search/skills/job-application-assistant/01-candidate-profile.md"
)
EVALUATION_FILE = Path(
    ".claude/skills/ai-job-search/skills/job-application-assistant/04-job-evaluation.md"
)


@dataclass
class ProfileText:
    text: str
    hash: str


def compose_profile_text(profile_file=PROFILE_FILE, evaluation_file=EVALUATION_FILE):
    profile_file = Path(profile_file)
    if not profile_file.exists():
        raise FileNotFoundError(
            f"Profile file not found: {profile_file}. Run /setup to generate it first."
        )
    text = profile_file.read_text()
    goals = _career_goals_block(Path(evaluation_file))
    if goals:
        text += "\n\n## Target Roles & Career Goals\n" + goals
    return ProfileText(text=text, hash=hashlib.sha256(text.encode()).hexdigest())


def _career_goals_block(evaluation_file):
    """Extract only the '**Career goals:**' bullet list — not the whole rubric."""
    if not evaluation_file.exists():
        return ""
    content = evaluation_file.read_text()
    match = re.search(r"\*\*Career goals:\*\*\n((?:- .*\n)+)", content)
    return match.group(1) if match else ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_profile_text.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/match/__init__.py src/job_dashboard/match/profile_text.py tests/test_profile_text.py
git commit -m "feat: compose and hash profile text for embedding-based matching"
```

---

### Task 3: `match/dedup.py` — mark cross-source duplicates

**Files:**
- Create: `src/job_dashboard/match/dedup.py`
- Test: `tests/test_dedup.py`

**Interfaces:**
- Consumes: `canonical_jobs_for_dedup(conn)`, `mark_duplicate(conn, job_id, canonical_id)` from `job_dashboard.db` (Task 1).
- Produces: `normalized_key(company: str, title: str) -> str`; `mark_duplicates(conn) -> int` (number of rows newly marked). Earliest-fetched row in a group (tie-broken by id) is canonical.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dedup.py
from job_dashboard.db import init_db, insert_job, suspected_duplicates
from job_dashboard.match.dedup import mark_duplicates, normalized_key
from job_dashboard.models import JobListing


def _job(source, title, company, url):
    return JobListing(source=source, title=title, company=company,
                      job_url=url, description="full jd text")


def test_normalized_key_strips_punctuation_and_case():
    assert normalized_key("Acme, Inc.", "Sr. ML Engineer") == \
        normalized_key("acme inc", "sr ml engineer")
    assert normalized_key("Acme", "ML Engineer") != normalized_key("Acme", "Data Engineer")


def test_same_role_across_sources_marks_later_as_duplicate(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job("jobspy:linkedin", "ML Engineer", "Acme", "https://li.com/1"))
    insert_job(conn, _job("remoteok", "ML Engineer", "Acme", "https://rok.com/2"))
    insert_job(conn, _job("remotive", "Data Scientist", "Beta", "https://rmt.com/3"))

    marked = mark_duplicates(conn)

    assert marked == 1
    dupes = suspected_duplicates(conn)
    assert len(dupes) == 1
    assert dupes[0]["source"] == "remoteok"
    assert dupes[0]["canonical_source"] == "jobspy:linkedin"


def test_near_miss_titles_are_not_merged(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job("a", "Senior ML Engineer", "Acme", "https://x.com/1"))
    insert_job(conn, _job("b", "ML Engineer", "Acme", "https://x.com/2"))

    assert mark_duplicates(conn) == 0


def test_mark_duplicates_is_idempotent(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job("a", "ML Engineer", "Acme", "https://x.com/1"))
    insert_job(conn, _job("b", "ML Engineer", "Acme", "https://x.com/2"))

    assert mark_duplicates(conn) == 1
    assert mark_duplicates(conn) == 0  # second run marks nothing new
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_dedup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'job_dashboard.match.dedup'`

- [ ] **Step 3: Implement**

```python
# src/job_dashboard/match/dedup.py
import re

from job_dashboard.db import canonical_jobs_for_dedup, mark_duplicate


def normalized_key(company, title):
    def norm(s):
        return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

    return f"{norm(company)}|{norm(title)}"


def mark_duplicates(conn):
    """Group canonical jobs by normalized (company, title); earliest-fetched row
    (tie-broken by id) stays canonical, the rest are marked duplicate_of it.
    Marked rows are never deleted — deletion is an explicit user command later."""
    groups = {}
    for job_id, company, title, fetched_at, _source in canonical_jobs_for_dedup(conn):
        groups.setdefault(normalized_key(company, title), []).append((fetched_at, job_id))

    marked = 0
    for rows in groups.values():
        if len(rows) < 2:
            continue
        rows.sort()
        canonical_id = rows[0][1]
        for _, dup_id in rows[1:]:
            mark_duplicate(conn, dup_id, canonical_id)
            marked += 1
    return marked
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_dedup.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/match/dedup.py tests/test_dedup.py
git commit -m "feat: mark cross-source duplicate listings by normalized company+title"
```

---

### Task 4: `match/embedder.py` — embed-score every canonical job

**Files:**
- Create: `src/job_dashboard/match/embedder.py`
- Modify: `requirements.txt` (add `sentence-transformers>=2.2`)
- Test: `tests/test_embedder.py`

**Interfaces:**
- Consumes: `jobs_needing_embed_score(conn, profile_hash)`, `upsert_embed_score(conn, job_id, embed_score, profile_hash)` from `job_dashboard.db` (Task 1).
- Produces:
  - `cosine(a: list[float], b: list[float]) -> float`
  - `compute_embed_scores(conn, model, profile_text: str, profile_hash: str) -> int` — model needs only `.encode(list[str]) -> list[vector]`
  - `load_default_model()` — lazy-imports sentence-transformers, returns `SentenceTransformer("all-MiniLM-L6-v2")`; raises `RuntimeError` with install instructions if not installed.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_embedder.py
import pytest

from job_dashboard.db import init_db, insert_job, top_unranked_jobs
from job_dashboard.match.embedder import compute_embed_scores, cosine
from job_dashboard.models import JobListing


class FakeModel:
    """Deterministic 'embeddings': known texts map to fixed vectors."""
    VECTORS = {
        "PROFILE": [1.0, 0.0],
        "ml job": [0.9, 0.1],     # close to profile
        "chef job": [0.0, 1.0],   # orthogonal to profile
    }

    def encode(self, texts):
        return [self.VECTORS[t] for t in texts]


def _job(n, description):
    return JobListing(source="s", title=f"T{n}", company=f"C{n}",
                      job_url=f"https://x.com/{n}", description=description)


def test_cosine_basics():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_compute_embed_scores_scores_all_unscored_and_orders_feed(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job(1, "ml job"))
    insert_job(conn, _job(2, "chef job"))

    scored = compute_embed_scores(conn, FakeModel(), "PROFILE", "hashA")

    assert scored == 2
    top = top_unranked_jobs(conn, limit=10)
    assert top[0]["description"] == "ml job"
    assert top[0]["embed_score"] > top[1]["embed_score"]


def test_compute_embed_scores_skips_already_scored(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job(1, "ml job"))
    compute_embed_scores(conn, FakeModel(), "PROFILE", "hashA")

    assert compute_embed_scores(conn, FakeModel(), "PROFILE", "hashA") == 0


def test_load_default_model_raises_actionable_error_without_dependency(monkeypatch):
    import builtins
    from job_dashboard.match import embedder

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.startswith("sentence_transformers"):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)

    with pytest.raises(RuntimeError, match="pip3 install sentence-transformers"):
        embedder.load_default_model()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_embedder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'job_dashboard.match.embedder'`

- [ ] **Step 3: Implement**

```python
# src/job_dashboard/match/embedder.py
import math

from job_dashboard.db import jobs_needing_embed_score, upsert_embed_score


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def compute_embed_scores(conn, model, profile_text, profile_hash):
    """Score every canonical job lacking a current-profile score. Returns count."""
    rows = jobs_needing_embed_score(conn, profile_hash)
    if not rows:
        return 0
    profile_vec = model.encode([profile_text])[0]
    descriptions = [description for _, description in rows]
    job_vecs = model.encode(descriptions)
    for (job_id, _), vec in zip(rows, job_vecs):
        upsert_embed_score(conn, job_id, cosine(profile_vec, vec), profile_hash)
    return len(rows)


def load_default_model():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise RuntimeError(
            "sentence-transformers is not installed. "
            "Install it with: pip3 install sentence-transformers"
        )
    return SentenceTransformer("all-MiniLM-L6-v2")
```

Append to `requirements.txt`:

```
sentence-transformers>=2.2
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_embedder.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/match/embedder.py tests/test_embedder.py requirements.txt
git commit -m "feat: embedding-similarity scoring with injectable model"
```

---

### Task 5: `pipeline.py` — orchestrate ingest → dedup → embed-score

**Files:**
- Create: `src/job_dashboard/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `run_ingest` (existing), `mark_duplicates` (Task 3), `compose_profile_text` (Task 2), `compute_embed_scores`, `load_default_model` (Task 4), `suspected_duplicates` (Task 1).
- Produces: `run_pipeline(conn, job_sources, company_sources, profile_file=None, evaluation_file=None, model_loader=load_default_model) -> dict` with keys `ingest` (run_ingest's dict), `duplicates_marked` (int), `suspected_duplicates` (list[dict]), `embed_scored` (int), `embed_skipped` (None or str reason). `profile_file`/`evaluation_file` of `None` mean the module defaults from `profile_text.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pipeline.py
from job_dashboard import pipeline
from job_dashboard.db import init_db
from job_dashboard.models import JobListing

PROFILE_MD = "# Profile\n- python ml\n"


class FakeModel:
    def encode(self, texts):
        return [[1.0, 0.0] for _ in texts]


def _sources():
    j1 = JobListing(source="a", title="ML Engineer", company="Acme",
                    job_url="https://a.com/1", description="ml work")
    j2 = JobListing(source="b", title="ML Engineer", company="Acme",
                    job_url="https://b.com/2", description="ml work again")
    return [lambda: [j1], lambda: [j2]]


def test_run_pipeline_ingests_dedups_and_scores(tmp_path):
    conn = init_db(tmp_path / "t.db")
    profile = tmp_path / "01.md"
    profile.write_text(PROFILE_MD)

    result = pipeline.run_pipeline(
        conn, job_sources=_sources(), company_sources=[],
        profile_file=profile, evaluation_file=tmp_path / "absent.md",
        model_loader=lambda: FakeModel(),
    )

    assert result["ingest"]["new_jobs"] == 2
    assert result["duplicates_marked"] == 1
    assert len(result["suspected_duplicates"]) == 1
    assert result["embed_scored"] == 1  # only the canonical row is scored
    assert result["embed_skipped"] is None


def test_run_pipeline_survives_missing_embedding_dependency(tmp_path):
    conn = init_db(tmp_path / "t.db")
    profile = tmp_path / "01.md"
    profile.write_text(PROFILE_MD)

    def broken_loader():
        raise RuntimeError("sentence-transformers is not installed. pip3 install ...")

    result = pipeline.run_pipeline(
        conn, job_sources=_sources(), company_sources=[],
        profile_file=profile, evaluation_file=tmp_path / "absent.md",
        model_loader=broken_loader,
    )

    assert result["ingest"]["new_jobs"] == 2       # ingest + dedup still ran
    assert result["duplicates_marked"] == 1
    assert result["embed_scored"] == 0
    assert "sentence-transformers" in result["embed_skipped"]


def test_run_pipeline_survives_missing_profile(tmp_path):
    conn = init_db(tmp_path / "t.db")

    result = pipeline.run_pipeline(
        conn, job_sources=_sources(), company_sources=[],
        profile_file=tmp_path / "missing.md", evaluation_file=tmp_path / "absent.md",
        model_loader=lambda: FakeModel(),
    )

    assert result["embed_scored"] == 0
    assert "/setup" in result["embed_skipped"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pipeline.py -v`
Expected: FAIL with `ImportError: cannot import name 'pipeline'` (module doesn't exist)

- [ ] **Step 3: Implement**

```python
# src/job_dashboard/pipeline.py
from job_dashboard.db import suspected_duplicates
from job_dashboard.ingest import run_ingest
from job_dashboard.match.dedup import mark_duplicates
from job_dashboard.match.embedder import compute_embed_scores, load_default_model
from job_dashboard.match.profile_text import (
    EVALUATION_FILE, PROFILE_FILE, compose_profile_text,
)


def run_pipeline(conn, job_sources, company_sources,
                 profile_file=None, evaluation_file=None,
                 model_loader=load_default_model):
    """ingest -> dedup -> embed-score. Embedding problems (missing dependency,
    missing profile) never abort ingest/dedup — they surface in embed_skipped."""
    ingest_result = run_ingest(conn, job_sources, company_sources)
    duplicates_marked = mark_duplicates(conn)

    embed_scored = 0
    embed_skipped = None
    try:
        profile = compose_profile_text(
            profile_file if profile_file is not None else PROFILE_FILE,
            evaluation_file if evaluation_file is not None else EVALUATION_FILE,
        )
        model = model_loader()
    except (RuntimeError, FileNotFoundError) as exc:
        embed_skipped = str(exc)
    else:
        embed_scored = compute_embed_scores(conn, model, profile.text, profile.hash)

    return {
        "ingest": ingest_result,
        "duplicates_marked": duplicates_marked,
        "suspected_duplicates": suspected_duplicates(conn),
        "embed_scored": embed_scored,
        "embed_skipped": embed_skipped,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_pipeline.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the whole suite**

Run: `python3 -m pytest`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/job_dashboard/pipeline.py tests/test_pipeline.py
git commit -m "feat: pipeline orchestrating ingest, dedup, and embed scoring"
```

---

### Task 6: `rank_io.py` CLI + `/rank` Claude Code command

**Files:**
- Create: `src/job_dashboard/rank_io.py`
- Create: `.claude/commands/rank.md`
- Test: `tests/test_rank_io.py`

**Interfaces:**
- Consumes: `top_unranked_jobs(conn, limit)`, `record_llm_evaluation(...)`, `init_db(path)` from `job_dashboard.db` (Task 1).
- Produces: CLI `python3 -m job_dashboard.rank_io top --db PATH [--limit N]` (prints JSON array) and `python3 -m job_dashboard.rank_io record --db PATH --job-id N --file EVAL_JSON` (writes one evaluation; exit 0 on success, exit 1 with the error on stderr for invalid payloads). `EVAL_JSON` schema: `{"llm_score": int, "verdict": str, "strengths": [str], "gaps": [str], "flags": {}}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rank_io.py
import json

import pytest

from job_dashboard import rank_io
from job_dashboard.db import init_db, insert_job, upsert_embed_score
from job_dashboard.models import JobListing


def _seed(tmp_path):
    db_path = tmp_path / "t.db"
    conn = init_db(db_path)
    insert_job(conn, JobListing(source="s", title="ML Engineer", company="Acme",
                                job_url="https://x.com/1", description="jd"))
    job_id = conn.execute("SELECT id FROM jobs").fetchone()[0]
    upsert_embed_score(conn, job_id, 0.9, "h")
    conn.close()
    return db_path, job_id


def test_top_prints_json_of_unranked_jobs(tmp_path, capsys):
    db_path, job_id = _seed(tmp_path)

    exit_code = rank_io.main(["top", "--db", str(db_path), "--limit", "5"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["id"] == job_id
    assert payload[0]["embed_score"] == 0.9


def test_record_writes_evaluation(tmp_path):
    db_path, job_id = _seed(tmp_path)
    eval_file = tmp_path / "eval.json"
    eval_file.write_text(json.dumps({
        "llm_score": 82, "verdict": "Strong Fit",
        "strengths": ["production ML"], "gaps": ["k8s"], "flags": {},
    }))

    exit_code = rank_io.main([
        "record", "--db", str(db_path), "--job-id", str(job_id),
        "--file", str(eval_file),
    ])

    assert exit_code == 0
    conn = init_db(db_path)
    row = conn.execute(
        "SELECT llm_score, verdict FROM match_scores WHERE job_id = ?", (job_id,)
    ).fetchone()
    assert row == (82, "Strong Fit")


def test_record_rejects_invalid_payload_with_exit_1(tmp_path, capsys):
    db_path, job_id = _seed(tmp_path)
    eval_file = tmp_path / "eval.json"
    eval_file.write_text(json.dumps({
        "llm_score": 999, "verdict": "Strong Fit",
        "strengths": [], "gaps": [], "flags": {},
    }))

    exit_code = rank_io.main([
        "record", "--db", str(db_path), "--job-id", str(job_id),
        "--file", str(eval_file),
    ])

    assert exit_code == 1
    assert "llm_score" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_rank_io.py -v`
Expected: FAIL with `ImportError: cannot import name 'rank_io'`

- [ ] **Step 3: Implement the CLI**

```python
# src/job_dashboard/rank_io.py
"""CLI bridge between the /rank Claude Code command and the SQLite database.

`top` prints the highest-embed-score canonical jobs that lack an LLM
evaluation; `record` writes one agent evaluation back. Keeping this as a CLI
means the /rank command shells out instead of embedding SQL in a skill file.
"""
import argparse
import json
import sys

from job_dashboard.db import init_db, record_llm_evaluation, top_unranked_jobs


def main(argv=None):
    parser = argparse.ArgumentParser(prog="rank_io")
    sub = parser.add_subparsers(dest="command", required=True)

    top = sub.add_parser("top", help="print top unranked jobs as JSON")
    top.add_argument("--db", required=True)
    top.add_argument("--limit", type=int, default=30)

    record = sub.add_parser("record", help="record one LLM evaluation")
    record.add_argument("--db", required=True)
    record.add_argument("--job-id", type=int, required=True)
    record.add_argument("--file", required=True, help="path to evaluation JSON")

    args = parser.parse_args(argv)
    conn = init_db(args.db)
    try:
        if args.command == "top":
            print(json.dumps(top_unranked_jobs(conn, args.limit), indent=2))
            return 0
        payload = json.loads(open(args.file).read())
        record_llm_evaluation(
            conn, args.job_id,
            llm_score=payload.get("llm_score"),
            verdict=payload.get("verdict"),
            strengths=payload.get("strengths", []),
            gaps=payload.get("gaps", []),
            flags=payload.get("flags", {}),
        )
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_rank_io.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Write the `/rank` command file**

```markdown
<!-- .claude/commands/rank.md -->
# /rank — Deep-rank top jobs against the profile

Score the highest-embedding-similarity unranked jobs with a full evaluation
against `.claude/skills/ai-job-search/skills/job-application-assistant/04-job-evaluation.md`.

## Steps

1. Fetch the batch (default 30; `$ARGUMENTS` may override with a number):

   ```bash
   python3 -m job_dashboard.rank_io top --db data/jobs.db --limit 30
   ```

   If the JSON array is empty, report "No unranked jobs — run the pipeline first" and stop.

2. Read `04-job-evaluation.md` once. For each job in the batch, dispatch a
   subagent (parallel, in groups of up to 5) whose prompt contains: the job's
   title/company/location/job_url/description JSON, the full text of the
   evaluation framework, and this output contract:

   > Evaluate this job against the framework's five dimensions and weighting.
   > Return ONLY a JSON object:
   > `{"llm_score": <int 0-100 weighted overall>, "verdict": "<Strong Fit|Good Fit|Moderate Fit|Weak Fit|Poor Fit>", "strengths": ["..."], "gaps": ["..."], "flags": {"deal_breakers": [], "deadline": null, "expired": false}}`

3. For each agent result, write it to a temp file and record it:

   ```bash
   python3 -m job_dashboard.rank_io record --db data/jobs.db --job-id <ID> --file <EVAL_JSON_PATH>
   ```

   A non-zero exit means the payload was invalid — retry that one agent once
   with the error message appended to its prompt; if it fails again, skip that
   job and continue (per-job isolation; one failure never aborts the batch).

4. Report a summary table: job title/company, llm_score, verdict — plus any
   skipped jobs and the count remaining unranked.
```

- [ ] **Step 6: Run the whole suite**

Run: `python3 -m pytest`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/job_dashboard/rank_io.py tests/test_rank_io.py .claude/commands/rank.md
git commit -m "feat: rank_io CLI and /rank command for LLM deep-ranking"
```

---

## What this plan does not cover (by design — see spec Non-goals)

- Dashboard UI (next subsystem; designed around these scores).
- Deleting duplicate rows — explicit user command later, after the logic is verified on real data.
- Embedding-similarity dedup, outcome-based score calibration, cron scheduling.
- Installing sentence-transformers' model weights (first live run downloads `all-MiniLM-L6-v2` automatically; tests never need it).
