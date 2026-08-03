# Naukri Chatbot Apply Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a hybrid Naukri apply to the Application Agent — a headless résumé push (NopeRi `update_resume` + verify) plus a reusable, paraphrase-matched Answer Bank that drafts grounded chatbot answers, pausing the candidate only for exceptional questions.

**Architecture:** Three new/extended Python modules in `src/job_dashboard/apply/` (`naukri_resume.py`, `naukri_answers.py`, extend `store.py`) plus a browser runbook. Pure logic, fully unit-tested with fakes; the browser step is manual per the runbook. Reuses existing seams: `draft_screening_answer`, `check_grounding`, the embedding model (`load_default_model`/`cosine`), `compose_profile_text`, `assemble_application_package`, and the source's NopeRi session-restore pattern.

**Tech Stack:** Python 3.11, stdlib `sqlite3`, `pytest`, sentence-transformers (all-MiniLM-L6-v2, already a dependency), vendored NopeRi (résumé-write only).

## Global Constraints

- Python 3.11; stdlib `sqlite3`; `pytest`; every file under 500 lines.
- Never fabricate; personal facts (CTC/notice/etc.) are never sent to the LLM and never guessed.
- Never auto-submit; the candidate sends the final chatbot message.
- On Naukri, typing into the chat box commits on Enter → the agent must **draft → candidate approves → then type**, per question. Never type before approval. (Runbook rule; enforced by procedure.)
- Naukri **source** (`sources/naukri_source.py`) stays read-only. NopeRi **résumé-write** (`update_resume`) is imported **only** in `apply/naukri_resume.py`; NopeRi apply/questionnaire code is never imported anywhere.
- Never apply on an unverified résumé — `push_resume` must return `ok=True` first.
- `apply/naukri_resume.py` and `apply/naukri_answers.py` never raise.
- Reuse the embedding model already in the project — no new model or dependency.

---

### Task 1: Extend `application_profile` with Naukri personal fields

**Files:**
- Modify: `src/job_dashboard/apply/store.py`
- Test: `tests/test_apply_store.py`

**Interfaces:**
- Consumes: existing `ensure_application_tables(conn)`, `save_application_profile(conn, fields)`, `get_application_profile(conn)`, `_PROFILE_COLS`.
- Produces: `application_profile` now round-trips `current_ctc` and `reason_for_change` (both nullable TEXT). No signature changes.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_apply_store.py`:

```python
def test_profile_roundtrips_naukri_ctc_and_reason(tmp_path):
    import sqlite3
    from job_dashboard.apply.store import (
        ensure_application_tables, save_application_profile, get_application_profile)
    conn = sqlite3.connect(tmp_path / "t.db")
    ensure_application_tables(conn)
    save_application_profile(conn, {
        "full_name": "Rakshit Singh",
        "current_ctc": "12 LPA",
        "reason_for_change": "Seeking deeper ML ownership",
    })
    p = get_application_profile(conn)
    assert p["current_ctc"] == "12 LPA"
    assert p["reason_for_change"] == "Seeking deeper ML ownership"


def test_add_column_guard_is_idempotent_on_existing_db(tmp_path):
    import sqlite3
    from job_dashboard.apply.store import ensure_application_tables
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    ensure_application_tables(conn)
    ensure_application_tables(conn)  # second call must not raise
    cols = {r[1] for r in conn.execute("PRAGMA table_info(application_profile)")}
    assert {"current_ctc", "reason_for_change"} <= cols
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_apply_store.py -k "naukri_ctc or idempotent" -v`
Expected: FAIL (`current_ctc` missing / KeyError).

- [ ] **Step 3: Implement the column additions**

In `src/job_dashboard/apply/store.py`, append the two columns to `_PROFILE_COLS`:

```python
_PROFILE_COLS = (
    "full_name", "email", "phone", "location", "linkedin_url", "github_url",
    "portfolio_url", "work_authorization", "years_experience",
    "willing_to_relocate", "notice_period", "salary_expectation",
    "current_ctc", "reason_for_change",
)
```

Add both to the `CREATE TABLE` body in `ensure_application_tables` (so fresh DBs have them):

```python
            salary_expectation TEXT, current_ctc TEXT, reason_for_change TEXT,
            updated_at TEXT
```

Then, after the `CREATE TABLE ... application_profile (...)` statement in `ensure_application_tables`, add an idempotent migration for already-existing DBs (mirrors the `duplicate_of` pattern in `db.py`):

```python
    existing = {r[1] for r in conn.execute("PRAGMA table_info(application_profile)")}
    for col in ("current_ctc", "reason_for_change"):
        if col not in existing:
            conn.execute(f"ALTER TABLE application_profile ADD COLUMN {col} TEXT")
```

(No change needed to `save_/get_application_profile` — they build their column list from `_PROFILE_COLS`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_apply_store.py -v`
Expected: PASS (all, including pre-existing store tests).

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/apply/store.py tests/test_apply_store.py
git commit -m "feat(apply): add current_ctc + reason_for_change to application_profile"
```

---

### Task 2: Résumé push — `apply/naukri_resume.py`

**Files:**
- Create: `src/job_dashboard/apply/naukri_resume.py`
- Test: `tests/test_naukri_resume.py`

**Interfaces:**
- Consumes: a cached Naukri session file (same one `sources/naukri_source.py` reads); NopeRi's `NaukriLoginClient.update_resume` / `fetch_profile_id` via a `client_factory` (injected in tests).
- Produces:
  - `@dataclass PushResult(ok: bool, live_resume_name: str|None, error: str|None)`
  - `push_resume(pdf_path, session_path=DEFAULT_SESSION_PATH, verify=True, client_factory=None, poll=(5, 0)) -> PushResult` — never raises. `poll=(attempts, delay_seconds)`; delay is `0` in tests.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_naukri_resume.py`:

```python
import json
from dataclasses import dataclass
from job_dashboard.apply import naukri_resume


@dataclass
class FakeUpdateResult:
    profile_id: str
    body: dict
    status_code: int


class FakeClient:
    """Mimics NopeRi's NaukriLoginClient surface used by push_resume."""
    def __init__(self, status=200, live_name="rakshit_ml.pdf", raise_on_update=False):
        self._status = status
        self._live_name = live_name
        self._raise = raise_on_update
    def update_resume(self, pdf_path):
        if self._raise:
            raise RuntimeError("token expired")
        return FakeUpdateResult("pid1", {"formKey": "f", "fileKey": "k"}, self._status)
    def current_resume_name(self):
        return self._live_name


def _session(tmp_path):
    p = tmp_path / "naukri_session.json"
    p.write_text(json.dumps({"token": "t", "cookies": {}}))
    return p


def test_push_and_verify_ok(tmp_path):
    sp = _session(tmp_path)
    r = naukri_resume.push_resume(
        "/tmp/rakshit_ml.pdf", session_path=sp, poll=(3, 0),
        client_factory=lambda s: FakeClient(status=200, live_name="rakshit_ml.pdf"))
    assert r.ok is True
    assert r.live_resume_name == "rakshit_ml.pdf"
    assert r.error is None


def test_verify_timeout_when_name_never_matches(tmp_path):
    sp = _session(tmp_path)
    r = naukri_resume.push_resume(
        "/tmp/rakshit_ml.pdf", session_path=sp, poll=(3, 0),
        client_factory=lambda s: FakeClient(status=200, live_name="old.pdf"))
    assert r.ok is False and r.error == "verify_timeout"


def test_upload_rejected_on_non_2xx(tmp_path):
    sp = _session(tmp_path)
    r = naukri_resume.push_resume(
        "/tmp/x.pdf", session_path=sp, poll=(3, 0),
        client_factory=lambda s: FakeClient(status=406))
    assert r.ok is False and r.error == "upload_rejected"


def test_no_session_file_short_circuits(tmp_path):
    calls = []
    r = naukri_resume.push_resume(
        "/tmp/x.pdf", session_path=tmp_path / "missing.json", poll=(3, 0),
        client_factory=lambda s: calls.append(1))
    assert r.ok is False and r.error == "no_session"
    assert calls == []  # factory never called


def test_client_exception_is_caught(tmp_path):
    sp = _session(tmp_path)
    r = naukri_resume.push_resume(
        "/tmp/x.pdf", session_path=sp, poll=(3, 0),
        client_factory=lambda s: FakeClient(raise_on_update=True))
    assert r.ok is False and r.error == "RuntimeError"


def test_verify_false_skips_readback(tmp_path):
    sp = _session(tmp_path)
    r = naukri_resume.push_resume(
        "/tmp/x.pdf", session_path=sp, verify=False, poll=(3, 0),
        client_factory=lambda s: FakeClient(status=200, live_name="anything.pdf"))
    assert r.ok is True and r.error is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_naukri_resume.py -v`
Expected: FAIL (`ModuleNotFoundError: naukri_resume`).

- [ ] **Step 3: Implement `push_resume`**

Create `src/job_dashboard/apply/naukri_resume.py`:

```python
"""Headless résumé push for the Naukri hybrid apply.

The ONLY module that imports NopeRi write code (update_resume). NopeRi's
apply / questionnaire / auto-apply-agent modules are never imported here.
Pushes the tailored résumé to the Naukri profile, then read-back-verifies it is
live before the browser step is allowed to apply (Naukri processes uploads
asynchronously — applying too early sends the old file). Never raises.
"""
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SESSION_PATH = Path("data/naukri_session.json")


@dataclass
class PushResult:
    ok: bool
    live_resume_name: str | None = None
    error: str | None = None


def _default_client_factory(session):
    """Build NopeRi's login client (which owns update_resume) from a cached
    session. Imported lazily so curl_cffi / NopeRi stay off everyone else's
    import path. Résumé-write surface only — never apply code."""
    import sys
    vendor = Path(__file__).resolve().parents[3] / "vendor" / "NopeRi"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    from job_dashboard.sources import naukri_session_shim  # noqa: F401 (registers restore_session)
    from src.client.naukri_client import NaukriLoginClient  # type: ignore
    login = NaukriLoginClient.__new__(NaukriLoginClient)
    login.restore_session(session)
    return login


def _status_ok(status):
    try:
        return 200 <= int(status) < 300
    except (TypeError, ValueError):
        return False


def _live_name(client):
    """Best-effort read of the résumé name Naukri currently reports live."""
    for attr in ("current_resume_name", "fetch_resume_name"):
        fn = getattr(client, attr, None)
        if callable(fn):
            return fn()
    return None


def push_resume(pdf_path, session_path=DEFAULT_SESSION_PATH, verify=True,
                client_factory=None, poll=(5, 2)):
    session_path = Path(session_path)
    if not session_path.exists():
        return PushResult(False, error="no_session")
    try:
        session = json.loads(session_path.read_text())
    except (OSError, ValueError):
        return PushResult(False, error="no_session")

    factory = client_factory or _default_client_factory
    try:
        client = factory(session)
        result = client.update_resume(pdf_path)
        if not _status_ok(getattr(result, "status_code", None)):
            return PushResult(False, error="upload_rejected")
        if not verify:
            return PushResult(True)

        want = os.path.basename(str(pdf_path)).lower()
        attempts, delay = poll
        for _ in range(max(1, int(attempts))):
            live = _live_name(client)
            if live and os.path.basename(str(live)).lower() == want:
                return PushResult(True, live_resume_name=live)
            if delay:
                time.sleep(delay)
        return PushResult(False, error="verify_timeout")
    except Exception as exc:  # blocked, token expired, API shape change, etc.
        logger.warning("Naukri résumé push failed: %s", type(exc).__name__)
        return PushResult(False, error=type(exc).__name__)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_naukri_resume.py -v`
Expected: PASS (all 6).

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/apply/naukri_resume.py tests/test_naukri_resume.py
git commit -m "feat(apply): naukri_resume.push_resume (NopeRi update_resume + read-back verify)"
```

---

### Task 3: Answer Bank + resolver — `apply/naukri_answers.py`

**Files:**
- Create: `src/job_dashboard/apply/naukri_answers.py`
- Test: `tests/test_naukri_answers.py`

**Interfaces:**
- Consumes: `draft_screening_answer(job, question, profile_text, research, resume_text="", llm=None)` from `apply/screening.py`; `cosine(a, b)` from `match/embedder.py`; an `embedder` object with `.encode(text) -> vector` (the model from `load_default_model()` in production, a fake in tests).
- Produces:
  - `@dataclass AnswerResult(text, source, needs_user, flag=None)`
  - `@dataclass BankEntry(intent, phrasing, text, source, vector=None)`
  - `SKILL_VOCAB: set[str]`, `MATCH_THRESHOLD = 0.60`
  - `build_answer_bank(package, profile_text=None, resume_text="", llm=None, embedder=None) -> list[BankEntry]`
  - `resolve_answer(question, bank, package=None, embedder=None) -> AnswerResult`

- [ ] **Step 1: Write the failing tests (incl. the paraphrase scenario table)**

Create `tests/test_naukri_answers.py`:

```python
import math
from job_dashboard.apply import naukri_answers as na


class FakeEmbedder:
    """Bag-of-words vectors over a tiny vocab so paraphrases that share content
    words land near each other. Deterministic; no model download."""
    VOCAB = ["python", "sql", "experience", "years", "notice", "relocate",
             "salary", "location", "favorite", "color", "blood", "group",
             "proficiency", "worked", "skill", "total", "work"]
    def encode(self, text):
        t = (text or "").lower()
        return [1.0 if w in t else 0.0 for w in self.VOCAB]


def _bank(profile=None, profile_text="Python and SQL. 3 years experience.",
          llm=None):
    pkg = {"profile": profile or {}, "job": {"title": "Data Scientist"},
           "resume": {"pdf_path": "/tmp/r.pdf"}}
    return na.build_answer_bank(pkg, profile_text=profile_text,
                                llm=llm or (lambda p: "3 years of hands-on Python."),
                                embedder=FakeEmbedder())


def test_bank_has_skill_entries_only_for_resume_skills():
    bank = _bank()
    intents = {e.intent for e in bank}
    assert "skill:python" in intents and "skill:sql" in intents
    assert "skill:java" not in intents  # java not in the profile text


def test_bank_has_personal_entry_only_when_field_set():
    bank = _bank(profile={"notice_period": "30 days"})
    intents = {e.intent for e in bank}
    assert "notice_period" in intents
    assert "current_ctc" not in intents  # unset -> no entry


def test_paraphrases_of_python_reuse_the_same_bank_answer():
    bank = _bank()
    emb = FakeEmbedder()
    phrasings = [
        "How many years of experience do you have in Python?",
        "What is your proficiency in Python?",
        "How long have you worked with Python?",
    ]
    results = [na.resolve_answer(q, bank, embedder=emb) for q in phrasings]
    assert all(r.source == "bank" and not r.needs_user for r in results)
    assert len({r.text for r in results}) == 1  # identical, reused answer


def test_skill_not_on_resume_pauses_without_calling_llm():
    calls = []
    bank = _bank(llm=lambda p: calls.append(p) or "should not be used")
    calls.clear()
    r = na.resolve_answer("Are you proficient in Java?", bank, embedder=FakeEmbedder())
    assert r.needs_user and r.flag == "skill_not_on_resume" and r.text == ""


def test_personal_set_returns_profile_value():
    bank = _bank(profile={"notice_period": "30 days"})
    r = na.resolve_answer("What is your notice period?", bank, embedder=FakeEmbedder())
    assert r.source == "profile" and r.text == "30 days" and not r.needs_user


def test_personal_unset_returns_blank_never_a_number_and_no_llm():
    spy = []
    bank = _bank(profile={}, llm=lambda p: spy.append(p) or "99 LPA")
    spy.clear()
    r = na.resolve_answer("What is your current CTC?", bank, embedder=FakeEmbedder())
    assert r.needs_user and r.flag == "no_stored_value" and r.text == ""
    assert spy == []  # personal facts never sent to the LLM at resolve time


def test_unmatched_question_is_exceptional():
    bank = _bank()
    r = na.resolve_answer("What is your favorite color?", bank, embedder=FakeEmbedder())
    assert r.needs_user and r.flag == "exceptional" and r.text == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_naukri_answers.py -v`
Expected: FAIL (`ModuleNotFoundError: naukri_answers`).

- [ ] **Step 3: Implement the Answer Bank + resolver**

Create `src/job_dashboard/apply/naukri_answers.py`:

```python
"""Reusable Answer Bank for Naukri's chatbot apply.

Precompute grounded answers per intent once, match each incoming question by
meaning (keyword first, then embedding similarity), reuse known answers, and pause
the candidate only for exceptional questions. Pure logic, no browser. Personal
facts come from the stored profile and are NEVER sent to the LLM. Never raises.
"""
from __future__ import annotations

from dataclasses import dataclass

from job_dashboard.apply.screening import draft_screening_answer
from job_dashboard.match.embedder import cosine

MATCH_THRESHOLD = 0.60

# Multi-word entries must be checked before their single-word substrings.
SKILL_VOCAB = [
    "machine learning", "deep learning", "computer vision", "time series",
    "power bi", "scikit-learn", "python", "sql", "scala", "spark", "hadoop",
    "tensorflow", "pytorch", "keras", "sklearn", "nlp", "llm", "genai", "aws",
    "azure", "gcp", "docker", "kubernetes", "tableau", "excel", "statistics",
    "java", "ml", "ai", "r",
]

# intent -> (profile key, canonical phrasing). Order = keyword-match priority.
_PERSONAL = [
    ("expected_ctc", "salary_expectation", "what is your expected ctc salary"),
    ("current_ctc", "current_ctc", "what is your current ctc salary"),
    ("notice_period", "notice_period", "what is your notice period"),
    ("willing_to_relocate", "willing_to_relocate", "are you willing to relocate"),
    ("reason_for_change", "reason_for_change", "what is your reason for change"),
    ("location", "location", "what is your current location"),
]
_PERSONAL_KEYWORDS = [
    ("expected_ctc", ("expected ctc", "expected salary", "expected compensation", "expected pay")),
    ("current_ctc", ("current ctc", "current salary", "present ctc", "current compensation", "current pay")),
    ("notice_period", ("notice period", "notice")),
    ("willing_to_relocate", ("relocat",)),
    ("reason_for_change", ("reason for change", "reason for leaving", "reason for switch",
                            "why do you want to change", "why are you looking")),
    ("location", ("current location", "your location", "where are you located",
                   "current city", "based out of")),
    ("total_experience", ("total experience", "years of experience", "work experience",
                           "overall experience", "how many years")),
]


@dataclass
class AnswerResult:
    text: str
    source: str            # "bank" | "profile" | "unanswered"
    needs_user: bool
    flag: str | None = None


@dataclass
class BankEntry:
    intent: str
    phrasing: str
    text: str
    source: str            # "bank" (résumé-derived) | "profile" (stored field)
    vector: object = None


def _skill_token(ql):
    for s in SKILL_VOCAB:
        if s in ql:
            return s
    return None


def _find(bank, intent):
    for e in bank:
        if e.intent == intent:
            return e
    return None


def _draft_skill_answer(skill, job, profile_text, resume_text, llm):
    q = f"How many years of experience do you have with {skill}?"
    try:
        res = draft_screening_answer(job, q, profile_text, None, resume_text, llm=llm)
    except Exception:
        return None
    if res.get("unsupported_company_claims") or "general_fallback" in (res.get("flags") or []):
        return None  # couldn't ground -> no entry -> resolve pauses the candidate
    return (res.get("answer") or "").strip() or None


def build_answer_bank(package, profile_text=None, resume_text="", llm=None, embedder=None):
    package = package or {}
    profile = package.get("profile") or {}
    job = package.get("job") or {}
    if profile_text is None:
        try:
            from job_dashboard.match.profile_text import compose_profile_text
            profile_text = compose_profile_text().text
        except Exception:
            profile_text = ""
    if llm is None:
        try:
            from job_dashboard.letter.draft import make_default_llm
            llm = make_default_llm()
        except Exception:
            llm = None

    entries: list[BankEntry] = []

    yrs = str(profile.get("years_experience") or "").strip()
    if yrs:
        entries.append(BankEntry("total_experience", "total years of work experience", yrs, "profile"))

    blob = f"{profile_text}\n{resume_text}".lower()
    resume_skills = [s for s in SKILL_VOCAB if s in blob]
    for s in resume_skills:
        if llm is None:
            continue
        ans = _draft_skill_answer(s, job, profile_text, resume_text, llm)
        if ans:
            entries.append(BankEntry(f"skill:{s}", f"years of experience with {s}", ans, "bank"))

    for intent, key, phrasing in _PERSONAL:
        val = profile.get(key)
        if key == "willing_to_relocate" and val is not None:
            val = "Yes" if val else "No"
        if val not in (None, ""):
            entries.append(BankEntry(intent, phrasing, str(val), "profile"))

    if embedder is not None:
        for e in entries:
            try:
                e.vector = embedder.encode(e.phrasing)
            except Exception:
                e.vector = None
    return entries


def _keyword_intent(ql):
    for intent, kws in _PERSONAL_KEYWORDS:
        if any(k in ql for k in kws):
            return intent
    return None


def resolve_answer(question, bank, package=None, embedder=None):
    ql = (question or "").strip().lower()
    if not ql:
        return AnswerResult("", "unanswered", True, "exceptional")

    # 1. Skill token — reuse if on résumé, else pause (never auto-answer).
    token = _skill_token(ql)
    if token:
        entry = _find(bank, f"skill:{token}")
        if entry:
            return AnswerResult(entry.text, "bank", False)
        return AnswerResult("", "unanswered", True, "skill_not_on_resume")

    # 2. Keyword intents (personal + total experience).
    intent = _keyword_intent(ql)
    if intent:
        entry = _find(bank, intent)
        if entry:
            return AnswerResult(entry.text, entry.source, False)
        return AnswerResult("", "unanswered", True, "no_stored_value")

    # 3. Semantic paraphrase fallback.
    if embedder is not None and bank:
        try:
            qv = embedder.encode(question)
            best, score = None, -1.0
            for e in bank:
                if e.vector is None:
                    continue
                c = cosine(qv, e.vector)
                if c > score:
                    best, score = e, c
            if best is not None and score >= MATCH_THRESHOLD:
                return AnswerResult(best.text, best.source, False)
        except Exception:
            pass

    # 4. Exceptional.
    return AnswerResult("", "unanswered", True, "exceptional")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_naukri_answers.py -v`
Expected: PASS (all 7, including the paraphrase-reuse scenario table).

- [ ] **Step 5: Verify `cosine` accepts plain lists**

Run: `python -c "from job_dashboard.match.embedder import cosine; print(cosine([1,0,1],[1,1,0]))"`
Expected: prints a float ~0.5. If it errors on lists (numpy-only), wrap the fake vectors — but the resolver must accept whatever `load_default_model().encode` returns; confirm by reading `embedder.cosine`. If `cosine` needs numpy, change `FakeEmbedder.encode` to return `numpy.array(...)` and re-run Step 4.

- [ ] **Step 6: Commit**

```bash
git add src/job_dashboard/apply/naukri_answers.py tests/test_naukri_answers.py
git commit -m "feat(apply): reusable Answer Bank + paraphrase-matched resolver for Naukri"
```

---

### Task 4: Browser runbook + live e2e

**Files:**
- Create: `docs/naukri-apply-runbook.md`

**Interfaces:**
- Consumes: `assemble_application_package(conn, job_id)`, `push_resume(...)`, `build_answer_bank(...)`, `resolve_answer(...)`.
- Produces: a human-followed procedure; no code.

- [ ] **Step 1: Write the runbook**

Create `docs/naukri-apply-runbook.md` documenting the exact live procedure, mirroring the Wellfound/Workday runbooks:

1. **Preconditions** — a valid cached Naukri session (`data/naukri_session.json`, via `scripts/naukri_login.py`); the candidate logged into Naukri in their real Chrome; a tailored résumé PDF for the job (`resumes_for_job` → `pdf_path`).
2. **Detect** — open the job. If the primary button is **"Apply on company site"**, stop and use the existing ATS runbook. If it is **"Apply"** (Naukri chatbot), continue.
3. **Push + verify résumé** — run `push_resume(pdf_path)`. If `ok=False`, **STOP** and report `error` (`no_session` / `upload_rejected` / `verify_timeout` / exception). Never proceed to Apply on `ok=False`.
4. **Build the bank** — `build_answer_bank(package)` (reuse a cached bank if the profile/résumé is unchanged).
5. **Apply — review BEFORE typing** — click Apply. For each chatbot question:
   - `resolve_answer(question, bank)`.
   - If `needs_user=False`: show the candidate the drafted answer; on their explicit OK, type it and let the chatbot advance.
   - If `needs_user=True` (`skill_not_on_resume` / `no_stored_value` / `exceptional`): the candidate types the answer themselves.
   - **Never type before the candidate approves that specific answer — the box commits on Enter.**
6. **Final send** — the candidate sends the last message. The agent never sends the final answer.
7. **No in-chat upload** — the résumé reaches the employer via step 3; if a job *does* show an upload control, use it and skip step 3.
8. **Record** — on success, `save_application(conn, job_id, resume_id=..., screening=[...], ats="naukri", status="applied")`.

- [ ] **Step 2: Run the full suite**

Run: `pytest tests/test_apply_store.py tests/test_naukri_resume.py tests/test_naukri_answers.py -v`
Expected: PASS (all).

- [ ] **Step 3: Live e2e (manual, with the candidate present)**

Follow the runbook against one real Naukri chatbot job. Confirm: résumé push verifies; known questions auto-draft and reuse across phrasings; a skill-not-on-résumé / novel question pauses; nothing is typed before approval; the candidate sends the final message. Capture a before-submit screenshot.

- [ ] **Step 4: Commit**

```bash
git add docs/naukri-apply-runbook.md
git commit -m "docs(apply): Naukri chatbot apply runbook (push+verify, review-before-typing)"
```

---

## Self-Review

- **Spec coverage:** résumé push+verify (Task 2) ✔; Answer Bank + intent matching + reuse + pause-on-exceptional (Task 3) ✔; personal fields `current_ctc`/`reason_for_change` (Task 1) ✔; review-before-typing + no-auto-submit + push-gates-apply (Task 4 runbook + constraints) ✔; NopeRi boundary isolated to `naukri_resume.py` (Task 2) ✔; paraphrase scenario table as a test (Task 3 Step 1) ✔.
- **Placeholder scan:** none — every step carries real code or an exact command.
- **Type consistency:** `PushResult`, `AnswerResult`, `BankEntry`, `build_answer_bank`, `resolve_answer` signatures match across the Interfaces blocks, the code, and the tests; `draft_screening_answer` is called with its real signature `(job, question, profile_text, research, resume_text="", llm=None)`.
- **Open risk pinned:** Task 3 Step 5 explicitly verifies `cosine` accepts the vector type the fake produces, with a fallback instruction — the one cross-module assumption worth checking at build time.
