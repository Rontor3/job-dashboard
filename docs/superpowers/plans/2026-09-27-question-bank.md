# Question Bank Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace vague answer recall (`learned_answers` + Chroma vault) with a seeded question bank whose retrieval is faithful: the LLM only picks *which* entry a question is; values come from the bank, profile, job row, or a deterministic rule.

**Architecture:** Two sqlite tables in `data/jobs.db` (`qbank_entry`, `qbank_wording`). Per field: clean label → split off escape word → exact wording / embedding shortlist / LLM pick-or-none → polarity + shape gates → band (confident fill · likely fill+flag · none). An adapter with the old `AnswerMemory` interface (`recall/record/record_corrections`) drops into the existing fill loop. The dashboard's existing Answers/Questions/AnswersUsed/Retrieval screens are repointed to the bank.

**Tech Stack:** Python 3 stdlib + sqlite3 + numpy, Chroma's bundled ONNX MiniLM (`chromadb.utils.embedding_functions.DefaultEmbeddingFunction`, already installed), FastAPI, React + vitest.

**Spec:** `docs/superpowers/specs/2026-09-26-question-bank-design.md`

## Global Constraints

- The LLM never writes a bank value; it may only return a shortlist letter or NONE (validated).
- Every weak result is a flag, never a silent fill. Submit stays human-gated (unchanged).
- `data/qbank_seed.json` contains **no answers** (PII stays in `jobs.db`, never committed).
- The bank grows **only** from human-confirmed choices on the dashboard.
- Superseded code is unwired and marked superseded in `docs/career-agent/ats-graph.json`, not deleted.
- Files under 500 lines. Commit per task. **No `Co-Authored-By` trailer** (project CLAUDE.md; `attribution.commit` is not set).
- Run Python tests with `PYTHONPATH=src python3 -m pytest …`; frontend with `cd frontend && npx vitest run …`.
- Baseline before starting: `PYTHONPATH=src python3 -m pytest tests/career_agent tests/test_qa_api.py -q` → 299 passed, 24 skipped.

## Deliberate deviations from the spec (found while planning)

1. **Junk-label rule:** spec said "<3 meaningful tokens = junk"; that would reject real labels like `Gender`, `Veteran Status`. Junk is instead: perception's `is_unlabeled`, a bare option word (`yes`/`no`…), an input name (`cards[…]`), or a label equal to one of its own options.
2. **Helper text** (`Field.description`) is scanned for the escape word only, not matched on (it's instruction noise).
3. **Threshold knob:** a new setting `qbank_confident_min` (default 80) instead of reusing `answer_confidence_min`, which already governs judgment-tier drafts (a 0–100 LLM self-score, a different scale).
4. **Option fit** reuses `screen_review._coerce_option` before the LLM matcher (it already does yes/no, "not a veteran", numeric ranges).
5. **`standard_answers.py` stays live** as a fallback inside `map_screen` and is *reused* by the `country_is_home` rule; it is not marked superseded yet. Retire after real runs show the bank covers it.
6. **`memory_router.py`** (used only by the MCP server tools) is left pointing at the old vault; the fill loop no longer uses it.
7. **Telegram "save as" choice deferred:** answers typed at run time are recorded per-application (`application_qa`); promotion into the bank happens on the dashboard (QuestionsPanel / AnswersUsed). Add the Telegram choice later if dashboard promotion proves too slow.

## File map

| File | Status | Responsibility |
|---|---|---|
| `src/career_agent/memory/qbank.py` | create | tables, CRUD, seed load, default embedder |
| `data/qbank_seed.json` | create | ~95 canonical questions, no answers |
| `src/career_agent/memory/qbank_rules.py` | create | deterministic rules + shape checks |
| `src/career_agent/memory/qbank_match.py` | create | clean/escape/match/bands/resolve/fit |
| `src/career_agent/memory/qbank_admin.py` | create | migrate `learned_answers`, calibrate thresholds |
| `scripts/qbank.py` | create | thin CLI: seed / migrate / calibrate |
| `src/career_agent/memory/qbank_memory.py` | create | `AnswerMemory`-compatible adapter + `explain` |
| `src/career_agent/orchestrator/qa_recorder.py` | modify | likely fills recorded as `needs_answer` |
| `src/job_dashboard/qa_store.py` | modify | `qbank_confident_min` setting, memory sources, by-band stats |
| `src/career_agent/browser/form_model.py`, `perception.py` | modify | `input_type`, `autocomplete` on `Field` |
| `src/career_agent/apply.py`, `orchestrator/graph.py` | modify | wire bank in, remove semantic tier |
| `src/job_dashboard/api/qa_routes.py`, `api/app.py` | modify | questionnaire API |
| `frontend/src/api.js`, `components/{AnswersTab,QuestionsPanel,AnswersUsed,RetrievalPanel,EntryPicker}.jsx` | modify/create | dashboard |
| `tests/conftest.py` | modify | `fake_embed`, `qbank_conn`, `make_field` fixtures |

---

### Task 1: Question bank store + seed file

**Files:**
- Create: `src/career_agent/memory/qbank.py`
- Create: `data/qbank_seed.json`
- Modify: `tests/conftest.py` (append fixtures)
- Test: `tests/career_agent/test_qbank.py`

**Interfaces:**
- Produces:
  - `qbank.norm(text) -> str` (re-export of `job_dashboard.qa_store.norm_key`)
  - `qbank.SEED_PATH: Path`
  - `qbank.ensure(conn) -> None`
  - `qbank.get_entry(conn, entry_id) -> dict | None` — keys: `id, question, topic, atype, answer, profile_ref, rule, slots(list), synonyms(dict), shape, status, updated_at`
  - `qbank.entries(conn, status="active") -> list[dict]`
  - `qbank.upsert_entry(conn, e: dict) -> None` (never touches `answer`/`status`)
  - `qbank.set_answer(conn, entry_id, answer) -> bool`, `qbank.set_status(conn, entry_id, status) -> bool`
  - `qbank.add_wording(conn, text, entry_id, vec, source, *, replace=False) -> bool`
  - `qbank.exact(conn, text) -> str | None`
  - `qbank.wordings(conn) -> list[tuple[str, str, np.ndarray]]` — `(norm_text, entry_id, unit_vec)`, active entries only
  - `qbank.wordings_for(conn, entry_id) -> list[str]`
  - `qbank.add_entry(conn, *, question, kind, answer, embed, topic="misc") -> str`
  - `qbank.load_seed(conn, embed, path=SEED_PATH) -> int`, `qbank.seed_if_empty(conn, embed, path=SEED_PATH) -> int`
  - `qbank.default_embed(texts: list[str]) -> np.ndarray` (n×384 float32, unit rows)
  - `embed` everywhere = callable `list[str] -> np.ndarray` of unit-norm rows.
  - Fixtures: `fake_embed`, `qbank_conn`, `make_field` (see Step 1).

- [ ] **Step 1: Add shared test fixtures**

Append to `tests/conftest.py`:

```python
# ── question bank fixtures (tests/career_agent/test_qbank*.py, tests/test_qa_api.py) ──
import re as _re
import sqlite3 as _sqlite3
import zlib as _zlib

import numpy as _np
import pytest


@pytest.fixture
def fake_embed():
    """Deterministic bag-of-words embedding (no ONNX): shared words -> similar vectors."""
    def embed(texts):
        out = _np.zeros((len(texts), 256), dtype="float32")
        for i, t in enumerate(texts):
            for tok in _re.findall(r"[a-z0-9]+", (t or "").lower()):
                out[i, _zlib.crc32(tok.encode()) % 256] += 1.0
        n = _np.linalg.norm(out, axis=1, keepdims=True)
        return out / _np.where(n == 0, 1, n)
    return embed


QBANK_ENTRIES = [
    {"id": "sponsorship_required", "question": "Will you require visa sponsorship?", "atype": "bool",
     "wordings": ["Do you need visa sponsorship to work here?"], "answer": "Yes",
     "synonyms": {"Yes": ["I will require sponsorship"]}},
    {"id": "hispanic_latino", "question": "Are you Hispanic or Latino?", "atype": "bool",
     "wordings": [], "answer": "No"},
    {"id": "race", "question": "Please identify your race", "atype": "choice",
     "wordings": ["Race"], "profile_ref": "ethnicity"},
    {"id": "home_address", "question": "What is your current residential address?", "atype": "text",
     "shape": "address", "wordings": ["Street address"], "answer": "C-12, Sector 5, Noida 201301"},
    {"id": "local_cities", "question": "Which cities can you work from without relocating?",
     "atype": "text", "wordings": [], "answer": "Noida, Delhi"},
    {"id": "work_location", "question": "What is the address from which you plan on working?",
     "atype": "text", "rule": "local_or_escape", "wordings": []},
    {"id": "notice_period", "question": "What is your notice period in days?", "atype": "number",
     "wordings": ["Notice period"], "answer": "30"},
    {"id": "linkedin_url", "question": "LinkedIn profile URL", "atype": "text", "shape": "url",
     "wordings": [], "answer": "linkedin.com/in/x"},
    {"id": "english_proficiency", "question": "How would you rate your English language skills?",
     "atype": "choice", "wordings": []},
]


@pytest.fixture
def qbank_conn(fake_embed):
    """In-memory bank with QBANK_ENTRIES (Task 1 must exist for this to import)."""
    from career_agent.memory import qbank
    c = _sqlite3.connect(":memory:")
    qbank.ensure(c)
    for e in QBANK_ENTRIES:
        qbank.upsert_entry(c, e)
        if e.get("answer"):
            qbank.set_answer(c, e["id"], e["answer"])
        for t in [e["question"], *e["wordings"]]:
            qbank.add_wording(c, t, e["id"], fake_embed([t])[0], "seed")
    return c


@pytest.fixture
def make_field():
    from career_agent.browser.form_model import Field

    def make(label, kind="text", options=(), description="", ref="#x", **kw):
        return Field(ref=ref, kind=kind, label=label, required=False,
                     options=list(options), description=description, **kw)
    return make
```

- [ ] **Step 2: Write the failing store tests**

Create `tests/career_agent/test_qbank.py`:

```python
import json
import sqlite3

from career_agent.memory import qbank

_ATYPES = {"bool", "choice", "text", "number", "date"}
_PROFILE_COLS = {"full_name", "email", "phone", "location", "linkedin_url", "github_url",
                 "portfolio_url", "work_authorization", "years_experience", "willing_to_relocate",
                 "notice_period", "salary_expectation", "current_ctc", "reason_for_change",
                 "gender", "ethnicity", "veteran_status", "disability_status", "postal_code"}


def _conn():
    c = sqlite3.connect(":memory:")
    qbank.ensure(c)
    return c


def test_reseed_keeps_answer_and_normalizes_exact(fake_embed, tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"entries": [{
        "id": "notice_period", "question": "What is your notice period?", "topic": "availability",
        "atype": "number", "wordings": ["Notice period"]}]}))
    c = _conn()
    assert qbank.load_seed(c, fake_embed, seed) == 1
    qbank.set_answer(c, "notice_period", "30")
    qbank.load_seed(c, fake_embed, seed)
    e = qbank.get_entry(c, "notice_period")
    assert e["answer"] == "30" and e["slots"] == [] and e["synonyms"] == {}
    assert qbank.exact(c, "Notice period?") == "notice_period"
    assert len(qbank.wordings(c)) == 2
    assert qbank.seed_if_empty(c, fake_embed, seed) == 0


def test_seed_cannot_steal_a_wording_but_human_repoint_can(fake_embed):
    c = _conn()
    for i in ("a", "b"):
        qbank.upsert_entry(c, {"id": i, "question": f"q {i}", "atype": "text"})
    v = fake_embed(["Where do you live?"])[0]
    assert qbank.add_wording(c, "Where do you live?", "a", v, "seed")
    assert not qbank.add_wording(c, "Where do you live?", "b", v, "seed")
    assert qbank.exact(c, "where do you live") == "a"
    qbank.add_wording(c, "Where do you live?", "b", v, "human", replace=True)
    assert qbank.exact(c, "where do you live") == "b"
    assert qbank.wordings_for(c, "b") == ["Where do you live?"]


def test_superseded_entries_are_invisible(fake_embed):
    c = _conn()
    qbank.upsert_entry(c, {"id": "x", "question": "Old?", "atype": "bool"})
    qbank.add_wording(c, "Old?", "x", fake_embed(["Old?"])[0], "seed")
    assert qbank.set_status(c, "x", "superseded")
    assert qbank.exact(c, "Old?") is None and qbank.wordings(c) == [] and qbank.entries(c) == []


def test_add_entry_makes_unique_ids(fake_embed):
    c = _conn()
    a = qbank.add_entry(c, question="Have you used Claude?", kind="radio_group", answer="Yes", embed=fake_embed)
    b = qbank.add_entry(c, question="Have you used Claude?", kind="text", answer="Yes", embed=fake_embed)
    assert (a, b) == ("have_you_used_claude", "have_you_used_claude_2")
    assert qbank.get_entry(c, a)["atype"] == "choice" and qbank.get_entry(c, a)["answer"] == "Yes"


def test_real_seed_file_is_valid(fake_embed):
    raw = json.loads(qbank.SEED_PATH.read_text())["entries"]
    assert len(raw) >= 90
    assert all("answer" not in e for e in raw), "seed must never carry answers"
    assert all(e["atype"] in _ATYPES for e in raw)
    assert {e["profile_ref"] for e in raw if e.get("profile_ref")} <= _PROFILE_COLS
    texts = [qbank.norm(t) for e in raw for t in [e["question"], *e.get("wordings", [])]]
    assert len(texts) == len(set(texts)), "a wording is listed twice"
    assert qbank.load_seed(_conn(), fake_embed) == len(raw)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_qbank.py -q`
Expected: FAIL — `ImportError: cannot import name 'qbank'`.

- [ ] **Step 4: Write `src/career_agent/memory/qbank.py`**

```python
"""Question bank store — canonical application questions and every confirmed
wording of them. Spec: docs/superpowers/specs/2026-09-26-question-bank-design.md

qbank_entry   one row per distinct question: type, the user's answer (or the
              profile column / rule that produces it), option synonyms, shape.
qbank_wording every wording confirmed to mean an entry, with its MiniLM vector:
              repeat wordings are exact hits, new ones are compared by meaning.

data/qbank_seed.json carries questions/wordings/rules but NEVER answers —
answers are typed on the dashboard and live only in jobs.db (PII stays local)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from job_dashboard.qa_store import norm_key as norm

SEED_PATH = Path(__file__).resolve().parents[3] / "data" / "qbank_seed.json"
_JSON_COLS = ("slots", "synonyms")
_DEF_COLS = ("question", "topic", "atype", "profile_ref", "rule", "slots", "synonyms", "shape")
_KIND_ATYPE = {"select": "choice", "radio_group": "choice", "combobox": "choice", "checkbox": "bool"}


def ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS qbank_entry (
        id TEXT PRIMARY KEY, question TEXT NOT NULL, topic TEXT, atype TEXT NOT NULL,
        answer TEXT, profile_ref TEXT, rule TEXT, slots TEXT, synonyms TEXT, shape TEXT,
        status TEXT NOT NULL DEFAULT 'active', updated_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS qbank_wording (
        norm TEXT PRIMARY KEY, entry_id TEXT NOT NULL, vec BLOB NOT NULL,
        source TEXT NOT NULL, text TEXT)""")
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(cur, r) -> dict:
    d = dict(zip([c[0] for c in cur.description], r))
    d["slots"] = json.loads(d["slots"]) if d.get("slots") else []
    d["synonyms"] = json.loads(d["synonyms"]) if d.get("synonyms") else {}
    return d


def get_entry(conn, entry_id):
    cur = conn.execute("SELECT * FROM qbank_entry WHERE id=?", (entry_id,))
    r = cur.fetchone()
    return _row(cur, r) if r else None


def entries(conn, status: str = "active") -> list[dict]:
    cur = conn.execute("SELECT * FROM qbank_entry WHERE status=? ORDER BY topic, id", (status,))
    return [_row(cur, r) for r in cur.fetchall()]


def upsert_entry(conn, e: dict) -> None:
    """Insert or refresh an entry's definition. Never touches `answer` or
    `status`, so re-seeding can't erase what the user typed or retired."""
    vals = [json.dumps(e[k]) if k in _JSON_COLS and e.get(k) is not None else e.get(k)
            for k in _DEF_COLS]
    conn.execute(
        f"INSERT INTO qbank_entry (id, {', '.join(_DEF_COLS)}, updated_at) "
        f"VALUES (?, {', '.join('?' * len(_DEF_COLS))}, ?) ON CONFLICT(id) DO UPDATE SET "
        f"{', '.join(f'{k}=excluded.{k}' for k in _DEF_COLS)}, updated_at=excluded.updated_at",
        [e["id"], *vals, _now()])
    conn.commit()


def set_answer(conn, entry_id, answer) -> bool:
    cur = conn.execute("UPDATE qbank_entry SET answer=?, updated_at=? WHERE id=?",
                       (None if answer is None else str(answer).strip(), _now(), entry_id))
    conn.commit()
    return cur.rowcount > 0


def set_status(conn, entry_id, status: str) -> bool:
    if status not in ("active", "superseded"):
        raise ValueError(status)
    cur = conn.execute("UPDATE qbank_entry SET status=?, updated_at=? WHERE id=?",
                       (status, _now(), entry_id))
    conn.commit()
    return cur.rowcount > 0


def add_wording(conn, text, entry_id, vec, source, *, replace=False) -> bool:
    """Link a wording to an entry. replace=False keeps an existing link (seed and
    migration must not undo a human re-point); replace=True moves it."""
    key = norm(text)
    if not key:
        return False
    verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
    cur = conn.execute(
        f"{verb} INTO qbank_wording (norm, entry_id, vec, source, text) VALUES (?,?,?,?,?)",
        (key, entry_id, np.asarray(vec, dtype="float32").tobytes(), source, text))
    conn.commit()
    return cur.rowcount > 0


def exact(conn, text):
    r = conn.execute(
        "SELECT w.entry_id FROM qbank_wording w JOIN qbank_entry e ON e.id=w.entry_id "
        "WHERE w.norm=? AND e.status='active'", (norm(text),)).fetchone()
    return r[0] if r else None


def wordings(conn) -> list:
    rows = conn.execute(
        "SELECT w.norm, w.entry_id, w.vec FROM qbank_wording w JOIN qbank_entry e "
        "ON e.id=w.entry_id WHERE e.status='active'").fetchall()
    return [(n, e, np.frombuffer(v, dtype="float32")) for n, e, v in rows]


def wordings_for(conn, entry_id) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT COALESCE(text, norm) FROM qbank_wording WHERE entry_id=? ORDER BY source, norm",
        (entry_id,))]


def new_entry_id(conn, question) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", norm(question)).strip("_")[:40] or "question"
    eid, n = base, 2
    while conn.execute("SELECT 1 FROM qbank_entry WHERE id=?", (eid,)).fetchone():
        eid, n = f"{base}_{n}", n + 1
    return eid


def add_entry(conn, *, question, kind, answer, embed, topic="misc") -> str:
    """A human-confirmed new question (dashboard 'save as new entry')."""
    eid = new_entry_id(conn, question)
    upsert_entry(conn, {"id": eid, "question": question, "topic": topic,
                        "atype": _KIND_ATYPE.get(kind, "text")})
    set_answer(conn, eid, answer)
    add_wording(conn, question, eid, embed([question])[0], "human", replace=True)
    return eid


def load_seed(conn, embed, path=SEED_PATH) -> int:
    data = json.loads(Path(path).read_text())
    for e in data["entries"]:
        upsert_entry(conn, e)
        texts = [e["question"], *e.get("wordings", [])]
        for t, v in zip(texts, embed(texts)):
            add_wording(conn, t, e["id"], v, "seed")
    return len(data["entries"])


def seed_if_empty(conn, embed, path=SEED_PATH) -> int:
    ensure(conn)
    if conn.execute("SELECT 1 FROM qbank_entry LIMIT 1").fetchone():
        return 0
    return load_seed(conn, embed, path)


_EF = None


def default_embed(texts):
    """Local MiniLM (Chroma's bundled ONNX model): no network, PII stays on-device."""
    global _EF
    if _EF is None:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        _EF = DefaultEmbeddingFunction()
    v = np.asarray(_EF(list(texts)), dtype="float32")
    return v / np.linalg.norm(v, axis=1, keepdims=True)
```

- [ ] **Step 5: Write `data/qbank_seed.json`**

```json
{
  "version": 1,
  "note": "Canonical application questions. NO ANSWERS here — answers are typed on the dashboard and live only in jobs.db. Load with: PYTHONPATH=src python3 scripts/qbank.py seed",
  "entries": [
    {"id": "sponsorship_required", "topic": "work_auth", "atype": "bool", "question": "Will you now or in the future require visa sponsorship to work for us?", "wordings": ["Will you require visa sponsorship?", "Do you need sponsorship for an employment visa (e.g. H-1B)?", "Will you require the company to sponsor your work visa?"], "synonyms": {"Yes": ["Yes, I will require sponsorship", "I will require sponsorship"], "No": ["No, I will not require sponsorship", "I do not require sponsorship"]}},
    {"id": "work_authorized_country", "topic": "work_auth", "atype": "bool", "rule": "country_is_home", "question": "Are you legally authorized to work in this country?", "wordings": ["Are you legally authorized to work in the United States?", "Do you have the right to work in India?", "Are you authorized to work in the country where this job is located?"]},
    {"id": "located_in_country", "topic": "work_auth", "atype": "bool", "rule": "country_is_home", "question": "Are you currently located in this country?", "wordings": ["Are you located in Canada?", "Do you currently reside in the United States?", "Are you currently based in India?"]},
    {"id": "citizenship", "topic": "work_auth", "atype": "choice", "question": "What is your country of citizenship?", "wordings": ["Citizenship", "Nationality"]},
    {"id": "current_visa_status", "topic": "work_auth", "atype": "text", "question": "What is your current visa or immigration status?", "wordings": ["Current work permit status"]},
    {"id": "security_clearance", "topic": "work_auth", "atype": "bool", "question": "Do you hold an active government security clearance?", "wordings": ["Do you currently have a security clearance?"]},
    {"id": "export_control_person", "topic": "work_auth", "atype": "bool", "question": "Are you a U.S. person as defined by export control regulations?", "wordings": ["Are you a U.S. citizen or permanent resident for export control purposes?"]},

    {"id": "current_ctc", "topic": "compensation", "atype": "number", "profile_ref": "current_ctc", "question": "What is your current CTC (in lakhs per annum)?", "wordings": ["Current CTC", "Current annual compensation", "What is your current salary?"]},
    {"id": "expected_ctc", "topic": "compensation", "atype": "number", "profile_ref": "salary_expectation", "question": "What is your expected CTC?", "wordings": ["Expected CTC", "What are your salary expectations?", "Desired salary", "Expected annual compensation"]},
    {"id": "ctc_negotiable", "topic": "compensation", "atype": "bool", "question": "Is your expected salary negotiable?", "wordings": ["Are your salary expectations flexible?"]},
    {"id": "ctc_fixed_component", "topic": "compensation", "atype": "number", "question": "What is the fixed component of your current CTC?", "wordings": ["Current fixed salary"]},
    {"id": "ctc_variable_component", "topic": "compensation", "atype": "number", "question": "What is the variable component of your current CTC?", "wordings": ["Current variable pay or bonus"]},
    {"id": "salary_currency", "topic": "compensation", "atype": "choice", "question": "In which currency is your salary?", "wordings": ["Salary currency"]},
    {"id": "other_offers", "topic": "compensation", "atype": "bool", "question": "Do you currently hold any other job offers?", "wordings": ["Do you have any offers in hand?"]},
    {"id": "other_offer_ctc", "topic": "compensation", "atype": "number", "question": "If you hold other offers, what CTC was offered?", "wordings": ["Offered CTC in hand"]},

    {"id": "notice_period", "topic": "availability", "atype": "number", "profile_ref": "notice_period", "question": "What is your notice period (in days)?", "wordings": ["Notice period", "How long is your notice period?", "What is your current notice period?"]},
    {"id": "notice_negotiable", "topic": "availability", "atype": "bool", "question": "Is your notice period negotiable or can it be bought out?", "wordings": ["Can you join earlier than your notice period?"]},
    {"id": "serving_notice", "topic": "availability", "atype": "bool", "question": "Are you currently serving your notice period?", "wordings": ["Are you on notice period?"]},
    {"id": "last_working_day", "topic": "availability", "atype": "date", "question": "What is your last working day?", "wordings": ["Last working date"]},
    {"id": "earliest_start", "topic": "availability", "atype": "text", "question": "When is the earliest you could start?", "wordings": ["When is the earliest you would want to start working with us?", "When can you start?", "Available start date", "Earliest joining date"]},
    {"id": "timeline_considerations", "topic": "availability", "atype": "text", "question": "Do you have any deadlines or timeline considerations we should be aware of?", "wordings": ["Are there any time constraints on your job search we should know about?"]},
    {"id": "currently_employed", "topic": "availability", "atype": "bool", "question": "Are you currently employed?", "wordings": ["Are you currently working?"]},
    {"id": "interview_availability", "topic": "availability", "atype": "text", "question": "When are you available for interviews?", "wordings": ["Interview availability"]},
    {"id": "time_zone", "topic": "availability", "atype": "text", "question": "What time zone are you in?", "wordings": ["Your time zone"]},
    {"id": "us_hours_overlap", "topic": "availability", "atype": "bool", "question": "Can you overlap with US working hours?", "wordings": ["Are you able to work partially in US time zones?"]},

    {"id": "home_address", "topic": "location", "atype": "text", "shape": "address", "question": "What is your current residential address?", "wordings": ["Street address", "Address line 1", "Current address", "Home address"]},
    {"id": "current_city", "topic": "location", "atype": "text", "profile_ref": "location", "question": "What is your current city?", "wordings": ["Current location", "Where are you currently based?"]},
    {"id": "postal_code", "topic": "location", "atype": "text", "profile_ref": "postal_code", "shape": "postcode", "question": "What is your postal code?", "wordings": ["PIN code", "ZIP code", "Postal code"]},
    {"id": "local_cities", "topic": "location", "atype": "text", "question": "Which cities can you work from without relocating?", "wordings": ["Cities you can work from without relocation"]},
    {"id": "preferred_locations", "topic": "location", "atype": "text", "question": "What are your preferred work locations?", "wordings": ["Preferred location", "Which locations are you open to working in?"]},
    {"id": "willing_to_relocate", "topic": "location", "atype": "bool", "profile_ref": "willing_to_relocate", "question": "Are you willing to relocate?", "wordings": ["Would you be open to relocating for this role?", "Are you open to relocation?"]},
    {"id": "work_location", "topic": "location", "atype": "text", "rule": "local_or_escape", "question": "What is the address from which you plan on working?", "wordings": ["Where will you be working from?", "Location you plan to work from"]},
    {"id": "onsite_ok", "topic": "location", "atype": "bool", "question": "Are you open to working in-person from the office?", "wordings": ["Are you open to working in-person in one of our offices 25% of the time?", "Are you comfortable working from the office 3 days a week?", "Are you able to work on-site?"]},
    {"id": "work_arrangement", "topic": "location", "atype": "choice", "question": "What is your preferred work arrangement (remote, hybrid or onsite)?", "wordings": ["Work mode preference"]},
    {"id": "travel_ok", "topic": "location", "atype": "bool", "question": "Are you willing to travel for work?", "wordings": ["Are you comfortable with occasional business travel?"]},
    {"id": "commute_ok", "topic": "location", "atype": "bool", "question": "Are you able to reliably commute to this job's location?", "wordings": ["Can you commute to the office location?"]},
    {"id": "shifts_ok", "topic": "location", "atype": "bool", "question": "Are you comfortable working night or rotational shifts?", "wordings": ["Are you open to working in shifts?"]},

    {"id": "total_experience_years", "topic": "experience", "atype": "number", "profile_ref": "years_experience", "question": "How many years of total work experience do you have?", "wordings": ["Total experience (years)", "Years of professional experience", "Total years of experience"]},
    {"id": "skill_years", "topic": "experience", "atype": "number", "rule": "years_in_skill", "slots": ["skill"], "question": "How many years of experience do you have with this skill?", "wordings": ["How many years of experience do you have with Python?", "Years of experience in SQL", "How many years of hands-on machine learning experience do you have?"]},
    {"id": "relevant_experience_years", "topic": "experience", "atype": "number", "question": "How many years of experience relevant to this role do you have?", "wordings": ["Relevant experience (years)"]},
    {"id": "highest_degree", "topic": "experience", "atype": "choice", "question": "What is your highest level of education?", "wordings": ["Highest qualification", "Highest degree obtained", "Education level"]},
    {"id": "degree_completed", "topic": "experience", "atype": "bool", "question": "Have you completed a bachelor's degree?", "wordings": ["Do you hold a bachelor's degree or higher?"]},
    {"id": "field_of_study", "topic": "experience", "atype": "text", "question": "What was your field of study?", "wordings": ["Major", "Discipline of study"]},
    {"id": "university", "topic": "experience", "atype": "text", "question": "Which university did you graduate from?", "wordings": ["College or university name", "Name of institution"]},
    {"id": "graduation_year", "topic": "experience", "atype": "number", "question": "What year did you graduate?", "wordings": ["Year of graduation", "Graduation year"]},
    {"id": "academic_score", "topic": "experience", "atype": "text", "question": "What was your CGPA or percentage in graduation?", "wordings": ["Graduation CGPA", "Academic score"]},
    {"id": "current_title", "topic": "experience", "atype": "text", "question": "What is your current job title?", "wordings": ["Current designation", "Current role"]},
    {"id": "current_employer", "topic": "experience", "atype": "text", "question": "Who is your current employer?", "wordings": ["Current company", "Current organization"]},
    {"id": "english_proficiency", "topic": "experience", "atype": "choice", "question": "How would you rate your English language skills?", "wordings": ["English proficiency level", "What is your level of English?"]},
    {"id": "languages_spoken", "topic": "experience", "atype": "text", "question": "Which languages do you speak?", "wordings": ["Languages known"]},
    {"id": "people_management", "topic": "experience", "atype": "bool", "question": "Do you have experience managing people?", "wordings": ["Have you managed a team before?"]},
    {"id": "team_size_managed", "topic": "experience", "atype": "number", "question": "How many people have you managed?", "wordings": ["Size of the team you managed"]},
    {"id": "cloud_platforms", "topic": "experience", "atype": "text", "question": "Which cloud platforms have you worked with?", "wordings": ["Cloud experience (AWS, GCP, Azure)"]},
    {"id": "certifications", "topic": "experience", "atype": "text", "question": "Do you hold any relevant certifications?", "wordings": ["Certifications"]},

    {"id": "interviewed_before", "topic": "background", "atype": "bool", "rule": "company_in_list", "slots": ["company"], "question": "Have you interviewed with this company before?", "wordings": ["Have you ever interviewed at Anthropic before?", "Have you previously interviewed with us?"]},
    {"id": "interviewed_recently", "topic": "background", "atype": "bool", "rule": "company_in_list", "slots": ["company"], "question": "Have you interviewed for this role in the last 3 months?", "wordings": ["Have you interviewed with us in the past 6 months?"]},
    {"id": "applied_before", "topic": "background", "atype": "bool", "rule": "company_in_list", "slots": ["company"], "question": "Have you previously applied to this company?", "wordings": ["Have you applied to a position with us before?"]},
    {"id": "worked_before", "topic": "background", "atype": "bool", "rule": "company_in_list", "slots": ["company"], "question": "Have you previously worked for this company?", "wordings": ["Are you a former employee of this company?", "Have you ever been employed by us?"]},
    {"id": "relatives_at_company", "topic": "background", "atype": "bool", "rule": "company_in_list", "slots": ["company"], "question": "Do you have relatives or close friends working at this company?", "wordings": ["Are you related to anyone employed by this company?"]},
    {"id": "conflict_of_interest", "topic": "background", "atype": "bool", "question": "Do you have any conflict of interest with this company?", "wordings": ["Are you related to anyone who has the authority to influence or sign commercial or government contracts with this company?", "In your current role, do you engage with this company's employees to negotiate or influence commercial or government contracts?"]},
    {"id": "referred", "topic": "background", "atype": "bool", "question": "Were you referred by a current employee?", "wordings": ["Do you have an employee referral?"]},
    {"id": "referrer_name", "topic": "background", "atype": "text", "question": "Who referred you?", "wordings": ["Referrer name", "Name of the employee who referred you"]},
    {"id": "referral_source", "topic": "background", "atype": "choice", "question": "How did you hear about this position?", "wordings": ["How did you hear about us?", "Source of application", "Where did you find this job?"]},
    {"id": "non_compete", "topic": "background", "atype": "bool", "question": "Are you bound by a non-compete or non-solicitation agreement?", "wordings": ["Do you have a non-compete agreement with your current employer?"]},
    {"id": "government_employee", "topic": "background", "atype": "bool", "question": "Are you a current or former government employee?", "wordings": ["Have you worked for a government entity in the last two years?"]},
    {"id": "background_check_ok", "topic": "background", "atype": "bool", "question": "Are you willing to undergo a background check?", "wordings": ["Will you consent to a background verification?"]},
    {"id": "criminal_record", "topic": "background", "atype": "bool", "question": "Have you ever been convicted of a criminal offense?", "wordings": ["Do you have any criminal convictions?"]},
    {"id": "age_18_plus", "topic": "background", "atype": "bool", "question": "Are you at least 18 years of age?", "wordings": ["Are you 18 or older?"]},
    {"id": "drug_test_ok", "topic": "background", "atype": "bool", "question": "Are you willing to take a pre-employment drug test?", "wordings": ["Will you submit to a drug screening?"]},
    {"id": "ai_policy_ack", "topic": "background", "atype": "bool", "question": "Do you acknowledge our policy on using AI in this application?", "wordings": ["AI Policy for Application"]},

    {"id": "gender", "topic": "demographics", "atype": "choice", "profile_ref": "gender", "question": "What is your gender?", "wordings": ["Gender", "Gender identity"], "synonyms": {"Male": ["Man", "Male", "Cisgender man"]}},
    {"id": "race", "topic": "demographics", "atype": "choice", "profile_ref": "ethnicity", "question": "Please identify your race", "wordings": ["Race", "Race/Ethnicity", "What is your racial or ethnic background?"], "synonyms": {"Asian": ["Asian (Not Hispanic or Latino)", "Asian or Asian American"]}},
    {"id": "hispanic_latino", "topic": "demographics", "atype": "bool", "question": "Are you Hispanic or Latino?", "wordings": ["Are you Hispanic/Latino?", "Hispanic or Latino ethnicity"]},
    {"id": "veteran_status", "topic": "demographics", "atype": "choice", "profile_ref": "veteran_status", "question": "What is your veteran status?", "wordings": ["Veteran Status", "Are you a protected veteran?"]},
    {"id": "disability_status", "topic": "demographics", "atype": "choice", "profile_ref": "disability_status", "question": "Do you have a disability?", "wordings": ["Disability Status", "Disability self-identification"]},
    {"id": "pronouns", "topic": "demographics", "atype": "text", "question": "What are your pronouns?", "wordings": ["Pronouns"]},
    {"id": "sexual_orientation", "topic": "demographics", "atype": "choice", "question": "What is your sexual orientation?", "wordings": ["Sexual orientation"]},
    {"id": "transgender", "topic": "demographics", "atype": "bool", "question": "Do you identify as transgender?", "wordings": ["Transgender identity"]},
    {"id": "date_of_birth", "topic": "demographics", "atype": "date", "question": "What is your date of birth?", "wordings": ["Date of birth", "DOB"]},
    {"id": "marital_status", "topic": "demographics", "atype": "choice", "question": "What is your marital status?", "wordings": ["Marital status"]},

    {"id": "phone_type", "topic": "misc", "atype": "choice", "question": "What type of phone number is this?", "wordings": ["Phone type", "Phone device type"]},
    {"id": "preferred_name", "topic": "misc", "atype": "text", "question": "What is your preferred name?", "wordings": ["Preferred name", "Preferred first name"]},
    {"id": "middle_name", "topic": "misc", "atype": "text", "rule": "empty_or_escape", "question": "What is your middle name?", "wordings": ["Middle name", "Middle name (if any)"]},
    {"id": "linkedin_url", "topic": "misc", "atype": "text", "profile_ref": "linkedin_url", "shape": "url", "question": "What is your LinkedIn profile URL?", "wordings": ["LinkedIn profile", "LinkedIn URL", "LinkedIn"]},
    {"id": "github_url", "topic": "misc", "atype": "text", "profile_ref": "github_url", "shape": "url", "question": "What is your GitHub profile URL?", "wordings": ["GitHub profile", "GitHub"]},
    {"id": "portfolio_url", "topic": "misc", "atype": "text", "profile_ref": "portfolio_url", "shape": "url", "question": "Do you have a portfolio or personal website?", "wordings": ["Portfolio URL", "Personal website", "Website"]},
    {"id": "reason_for_change", "topic": "misc", "atype": "text", "profile_ref": "reason_for_change", "question": "Why are you looking for a change?", "wordings": ["Reason for leaving your current job", "Reason for job change", "Why do you want to leave your current role?"]},
    {"id": "passport_valid", "topic": "misc", "atype": "bool", "question": "Do you have a valid passport?", "wordings": ["Do you hold a valid passport?"]},
    {"id": "driving_license", "topic": "misc", "atype": "bool", "question": "Do you have a valid driver's license?", "wordings": ["Driving licence"]},
    {"id": "home_office_setup", "topic": "misc", "atype": "bool", "question": "Do you have a laptop and reliable internet for remote work?", "wordings": ["Do you have a suitable home office setup?"]},
    {"id": "contract_ok", "topic": "misc", "atype": "bool", "question": "Are you open to a contract role?", "wordings": ["Would you consider a contract-to-hire position?"]},
    {"id": "full_time_ok", "topic": "misc", "atype": "bool", "question": "Are you looking for a full-time role?", "wordings": ["Are you available for full-time employment?"]},
    {"id": "sms_consent", "topic": "misc", "atype": "bool", "question": "Do you agree to receive text messages about your application?", "wordings": ["SMS opt-in"]},
    {"id": "whatsapp_ok", "topic": "misc", "atype": "bool", "question": "Can we contact you on WhatsApp?", "wordings": ["WhatsApp updates opt-in"]}
  ]
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_qbank.py -q`
Expected: 5 passed. (If `test_real_seed_file_is_valid` reports a duplicate wording, remove the duplicate from the seed.)

- [ ] **Step 7: Commit**

```bash
git add src/career_agent/memory/qbank.py data/qbank_seed.json tests/conftest.py tests/career_agent/test_qbank.py
git commit -m "feat(qbank): question bank store + answer-free seed of ~95 canonical questions"
```

---

### Task 2: Answer rules + shape checks

**Files:**
- Create: `src/career_agent/memory/qbank_rules.py`
- Test: `tests/career_agent/test_qbank_rules.py`

**Interfaces:**
- Consumes: `qbank.SEED_PATH` (Task 1); `career_agent.orchestrator.standard_answers.answer(purpose, label)` (existing).
- Produces:
  - `RuleCtx(question: str, answer: str|None, escape: str|None, job: dict, bank: Callable[[str], str|None])`
  - `RULES: dict[str, Callable[[RuleCtx], str|None]]` — keys `local_or_escape, empty_or_escape, country_is_home, company_in_list, years_in_skill`
  - `NO_INPUT_RULES: set[str]` — rules needing no answer typed on the entry itself
  - `RULE_HELP: dict[str, str]` — dashboard hint per rule
  - `infer_shape(entry_shape, input_type, autocomplete, label) -> str|None`
  - `shape_ok(shape, value, escape=None) -> bool`

- [ ] **Step 1: Write the failing tests**

Create `tests/career_agent/test_qbank_rules.py`:

```python
import json

from career_agent.memory.qbank import SEED_PATH
from career_agent.memory.qbank_rules import (NO_INPUT_RULES, RULE_HELP, RULES, RuleCtx,
                                             infer_shape, shape_ok)

BANK = {"home_address": "C-12, Sector 5, Noida 201301", "local_cities": "Noida, Delhi, Gurugram"}


def ctx(question="", answer=None, escape=None, job=None, bank=None):
    b = bank or {}
    return RuleCtx(question, answer, escape, job or {}, lambda eid: b.get(eid))


def test_local_or_escape():
    r = RULES["local_or_escape"]
    assert r(ctx(escape="relocating", job={"location": "San Francisco, CA"}, bank=BANK)) == "relocating"
    assert r(ctx(escape="relocating", job={"location": "Noida, Uttar Pradesh, India"}, bank=BANK)) == BANK["home_address"]
    assert r(ctx(escape="relocating", job={"location": "Remote, US"}, bank=BANK)) == BANK["home_address"]
    assert r(ctx(escape="relocating", job={}, bank=BANK)) is None           # unknown job city -> flag
    assert r(ctx(escape=None, job={"location": "London"}, bank=BANK)) is None  # not local, no escape -> flag


def test_empty_or_escape():
    r = RULES["empty_or_escape"]
    assert r(ctx(answer="none", escape="N/A")) == "N/A"
    assert r(ctx(answer="Kumar", escape="N/A")) == "Kumar"
    assert r(ctx(answer=None, escape="N/A")) is None                      # unanswered -> flag
    assert r(ctx(answer="none", escape=None)) is None


def test_company_in_list():
    r = RULES["company_in_list"]
    assert r(ctx(answer="none", job={"company": "Anthropic"})) == "No"
    assert r(ctx(answer="Google, Anthropic", job={"company": "Anthropic PBC"})) == "Yes"
    assert r(ctx(answer=None, job={"company": "Anthropic"})) is None
    assert r(ctx(answer="none", job={})) is None


def test_country_is_home_reuses_work_auth_logic():
    r = RULES["country_is_home"]
    assert r(ctx("Are you located in Canada?")) == "No"
    assert r(ctx("Are you legally authorized to work in India?")) == "Yes"
    assert r(ctx("Are you authorized to work in this country?")) is None


def test_years_in_skill():
    r = RULES["years_in_skill"]
    table = "python=3, machine learning=3, pytorch=2, default=2"
    assert r(ctx("How many years of experience do you have with PyTorch?", table)) == "2"
    assert r(ctx("Years of Python experience", table)) == "3"
    assert r(ctx("Years of experience with Rust", table)) == "2"
    assert r(ctx("Years with Rust", "python=3")) is None
    assert r(ctx("Years with Rust", None)) is None


def test_shapes():
    assert infer_shape(None, "email", "", "") == "email"
    assert infer_shape(None, "", "shipping address-line1", "") == "address"
    assert infer_shape(None, "", "", "Street address, line 1") == "address"
    assert infer_shape("url", "tel", "", "") == "url"                      # entry shape wins
    assert infer_shape(None, "", "", "Where will you work from?") is None
    assert not shape_ok("address", "relocating")
    assert shape_ok("address", "relocating", escape="relocating")
    assert shape_ok("address", "C-12, Sector 5, Noida")
    assert not shape_ok("number", "30 LPA") and shape_ok("number", "30")
    assert not shape_ok("phone", "https://x") and shape_ok(None, "anything")


def test_seed_only_uses_known_rules():
    used = {e["rule"] for e in json.loads(SEED_PATH.read_text())["entries"] if e.get("rule")}
    assert used <= set(RULES) and NO_INPUT_RULES <= set(RULES) and set(RULE_HELP) == set(RULES)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_qbank_rules.py -q`
Expected: FAIL — `ModuleNotFoundError: career_agent.memory.qbank_rules`.

- [ ] **Step 3: Write `src/career_agent/memory/qbank_rules.py`**

```python
"""Deterministic answer rules and text-shape checks for the question bank.

A rule turns an entry into a value for THIS job; it returns None when it can't
decide (unknown job city, entry unanswered) — None always means "flag it",
never a guess. Rules are plain Python so no answer logic lives in the DB."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

_NONE_WORDS = {"", "none", "n/a", "na", "-"}


@dataclass
class RuleCtx:
    question: str                      # the page's question, escape instruction removed
    answer: str | None                 # this entry's own stored answer (a list, a table…)
    escape: str | None                 # word the page asked to type ("relocating"), if any
    job: dict                          # jobs row for this run: company, location
    bank: Callable[[str], str | None]  # entry id -> resolved answer of another entry


def _items(s) -> list[str]:
    return [x.strip().lower() for x in re.split(r"[,;\n]", s or "")
            if x.strip().lower() not in _NONE_WORDS]


def local_or_escape(c: RuleCtx):
    """Job in a local city (or remote) -> home address; elsewhere -> the page's
    escape word ("relocating"). Unknown job location -> None."""
    loc = (c.job.get("location") or "").lower()
    if not loc:
        return None
    if "remote" in loc or any(city in loc for city in _items(c.bank("local_cities"))):
        return c.bank("home_address")
    return c.escape


def empty_or_escape(c: RuleCtx):
    """Your value, or the page's escape word ("N/A") when you have none."""
    if c.answer is None:
        return None
    if c.answer.strip().lower() in _NONE_WORDS:
        return c.escape
    return c.answer


def country_is_home(c: RuleCtx):
    """Yes if the question names India only, No if it names another country,
    None if neither/both (same logic as standard_answers work_authorization)."""
    from ..orchestrator.standard_answers import answer
    return answer("work_authorization", c.question)


def company_in_list(c: RuleCtx):
    """Entry answer = companies where the answer is Yes (or 'none')."""
    company = (c.job.get("company") or "").strip().lower()
    if not company or c.answer is None:
        return None
    return "Yes" if any(x in company for x in _items(c.answer)) else "No"


def years_in_skill(c: RuleCtx):
    """Entry answer = 'python=3, sql=3, default=2'; first skill named wins."""
    table = {}
    for part in re.split(r"[,;\n]", c.answer or ""):
        if "=" in part:
            k, v = part.split("=", 1)
            table[k.strip().lower()] = v.strip()
    q = (c.question or "").lower()
    for skill, yrs in table.items():
        if skill != "default" and re.search(rf"\b{re.escape(skill)}\b", q):
            return yrs
    return table.get("default")


RULES = {f.__name__: f for f in (local_or_escape, empty_or_escape, country_is_home,
                                 company_in_list, years_in_skill)}
NO_INPUT_RULES = {"local_or_escape", "country_is_home"}
RULE_HELP = {
    "local_or_escape": "Worked out per job: your home address if the job is in one of your local cities or remote, otherwise the word the form asks for (e.g. \"relocating\").",
    "empty_or_escape": "Your value, or 'none' if you don't have one (the form's N/A word is used then).",
    "country_is_home": "Worked out per question: Yes for India, No for any other country named.",
    "company_in_list": "Companies where the answer is Yes, comma-separated — or 'none'.",
    "years_in_skill": "skill=years pairs, e.g. python=3, sql=3, default=2",
}

# ── shapes ──────────────────────────────────────────────────────────────────
SHAPES = {
    "email": lambda v: bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.\w+", v)),
    "phone": lambda v: len(re.sub(r"\D", "", v)) >= 10,
    "url": lambda v: v.startswith(("http://", "https://")),
    "number": lambda v: bool(re.fullmatch(r"\d+(\.\d+)?", v)),
    "postcode": lambda v: bool(re.fullmatch(r"\d{6}", v)),
    "date": lambda v: bool(re.search(r"\d", v)),
    "address": lambda v: len(v.split()) >= 3 and bool(re.search(r"\d", v)),
}
_INPUT_TYPE = {"email": "email", "tel": "phone", "url": "url", "number": "number", "date": "date"}
_AUTOCOMPLETE = {"street-address": "address", "address-line1": "address", "postal-code": "postcode",
                 "tel": "phone", "email": "email", "url": "url"}
_LABEL = [(r"\bstreet\b|\baddress line\b", "address"), (r"\bpin ?code\b|\bpostal code\b|\bzip\b", "postcode"),
          (r"\bphone\b|\bmobile number\b", "phone"), (r"\be-?mail\b", "email")]


def infer_shape(entry_shape, input_type, autocomplete, label):
    """Entry's declared shape, else what the page declares (input type,
    autocomplete token), else label words. None = no clue -> nothing to check."""
    token = (autocomplete or "").split()[-1] if autocomplete else ""
    return (entry_shape or _INPUT_TYPE.get(input_type or "") or _AUTOCOMPLETE.get(token)
            or next((s for p, s in _LABEL if re.search(p, label or "", re.I)), None))


def shape_ok(shape, value, escape=None) -> bool:
    if not shape or value is None:
        return True
    if escape and str(value).strip().lower() == escape.strip().lower():
        return True                       # the page itself allowed this word
    check = SHAPES.get(shape)
    return True if check is None else check(str(value).strip())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_qbank_rules.py -q`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/memory/qbank_rules.py tests/career_agent/test_qbank_rules.py
git commit -m "feat(qbank): deterministic answer rules (relocating/N-A escape, company list, skill years) + shape checks"
```

---

### Task 3: Retrieval — clean, escape word, match, bands, resolve, fit

**Files:**
- Create: `src/career_agent/memory/qbank_match.py`
- Test: `tests/career_agent/test_qbank_match.py`

**Interfaces:**
- Consumes: `qbank.*` (Task 1), `RULES, RuleCtx, infer_shape, shape_ok` (Task 2), `career_agent.browser.perception.is_unlabeled(field)`, `career_agent.orchestrator.screen_review._coerce_option(value, options)`, `career_agent.orchestrator.judgment.match_value_to_option(label, value, options, llm)`.
- Produces:
  - constants `FLOOR, MARGIN, DEFAULT_HIGH`, bands `CONFIDENT="confident", LIKELY="likely", NONE="none"`
  - `Match(band, entry_id=None, score=0.0, kind="none", candidates=[(entry_id, score)], escape=None, note="")`; `kind ∈ {"exact","shortlist","llm","none"}`
  - `split_escape(label, description="") -> (question, escape|None)`
  - `is_junk(field) -> bool`
  - `llm_pick(question, entry_ids, conn, llm) -> entry_id|None`
  - `match_question(conn, question, *, embed, llm=None, high=DEFAULT_HIGH, floor=FLOOR, margin=MARGIN) -> Match`
  - `resolve_value(conn, entry, *, question, escape, job, contact) -> str|None`
  - `fit_option(label, value, options, synonyms, llm=None) -> str|None`
  - `answer_field(conn, field, *, embed, llm=None, job=None, contact=None, high=DEFAULT_HIGH) -> (Match, value|None)`
  - `llm` everywhere = callable `prompt:str -> str` (e.g. `job_dashboard.letter.draft.make_default_llm()`).

- [ ] **Step 1: Write the failing tests**

Create `tests/career_agent/test_qbank_match.py`:

```python
from career_agent.memory.qbank_match import (CONFIDENT, LIKELY, NONE, answer_field, is_junk,
                                             llm_pick, match_question, split_escape)

RELOC = ('What is the address from which you plan on working? '
         'If you would need to relocate, please type "relocating".')


def test_split_escape():
    assert split_escape(RELOC) == ("What is the address from which you plan on working?", "relocating")
    assert split_escape("Middle name", 'Enter "N/A" if none') == ("Middle name", "N/A")
    assert split_escape("Street address") == ("Street address", None)


def test_junk_labels(make_field):
    assert is_junk(make_field("yes")) and is_junk(make_field("cards[184c][field3]"))
    assert is_junk(make_field("")) and is_junk(make_field("Male", "radio_group", ["Male", "Female"]))
    assert not is_junk(make_field("Gender")) and not is_junk(make_field("Veteran Status"))


def test_exact_wording_is_confident(qbank_conn, fake_embed):
    m = match_question(qbank_conn, "Notice period?", embed=fake_embed)
    assert (m.band, m.entry_id, m.kind, m.score) == (CONFIDENT, "notice_period", "exact", 1.0)


def test_unrelated_question_is_none_but_logs_candidates(qbank_conn, fake_embed):
    m = match_question(qbank_conn, "Describe your favourite hobby outside work", embed=fake_embed)
    assert m.band == NONE and m.entry_id is None and m.candidates


def test_ambiguous_goes_to_llm_which_may_say_none(qbank_conn, fake_embed):
    prompts = []
    m = match_question(qbank_conn, "Do you need sponsorship for a visa?", embed=fake_embed,
                       llm=lambda p: prompts.append(p) or "NONE", high=0.99)
    assert prompts and (m.band, m.kind, m.entry_id) == (NONE, "llm", None)


def test_llm_pick_marks_likely(qbank_conn, fake_embed):
    m = match_question(qbank_conn, "Do you need sponsorship for a visa?", embed=fake_embed,
                       llm=lambda p: "a", high=0.99)
    assert (m.band, m.entry_id) == (LIKELY, "sponsorship_required")


def test_llm_pick_is_validated(qbank_conn):
    ids = ["race", "hispanic_latino"]
    assert llm_pick("q", ids, qbank_conn, lambda p: "(b)") == "hispanic_latino"
    assert llm_pick("q", ids, qbank_conn, lambda p: "<think>hmm</think>a") == "race"
    assert llm_pick("q", ids, qbank_conn, lambda p: "Asian") is None      # a value, not a letter
    assert llm_pick("q", ids, qbank_conn, lambda p: "c") is None          # out of range
    assert llm_pick("q", ids, qbank_conn, None) is None


def test_polarity_difference_caps_at_likely(qbank_conn, fake_embed):
    m = match_question(qbank_conn, "Will you not require visa sponsorship?", embed=fake_embed, high=0.5)
    assert (m.entry_id, m.band) == ("sponsorship_required", LIKELY) and "polarity" in m.note


def test_relocating_flow(qbank_conn, fake_embed, make_field):
    f = make_field(RELOC)
    m, v = answer_field(qbank_conn, f, embed=fake_embed, job={"location": "San Francisco, CA"})
    assert (m.band, m.entry_id, m.escape, v) == (CONFIDENT, "work_location", "relocating", "relocating")
    _, v = answer_field(qbank_conn, f, embed=fake_embed, job={"location": "Noida, India"})
    assert v == "C-12, Sector 5, Noida 201301"


def test_profile_ref_and_unanswered(qbank_conn, fake_embed, make_field):
    m, v = answer_field(qbank_conn, make_field("Race"), embed=fake_embed, contact={"ethnicity": "Asian"})
    assert (m.entry_id, v) == ("race", "Asian")
    m, v = answer_field(qbank_conn, make_field("Race"), embed=fake_embed, contact={})
    assert (m.band, v, m.note) == (NONE, None, "no answer for entry")


def test_shape_failure_caps_at_likely(qbank_conn, fake_embed, make_field):
    m, v = answer_field(qbank_conn, make_field("LinkedIn profile URL"), embed=fake_embed)
    assert (m.band, v) == (LIKELY, "linkedin.com/in/x") and "shape url" in m.note


def test_option_fit(qbank_conn, fake_embed, make_field):
    f = make_field("Will you require visa sponsorship?", "select",
                   ["I will require sponsorship", "I do not require sponsorship"])
    assert answer_field(qbank_conn, f, embed=fake_embed)[1] == "I will require sponsorship"
    f = make_field("Are you Hispanic or Latino?", "radio_group", ["Yes", "No", "Decline"])
    assert answer_field(qbank_conn, f, embed=fake_embed)[1] == "No"
    f = make_field("Will you require visa sponsorship?", "select", ["Option A", "Option B"])
    m, v = answer_field(qbank_conn, f, embed=fake_embed)         # nothing fits, no LLM -> flag
    assert (m.band, v) == (NONE, None)


def test_non_bank_fields_skipped(qbank_conn, fake_embed, make_field):
    assert answer_field(qbank_conn, make_field("Resume", "file"), embed=fake_embed)[0].note == "not a bank field"
    assert answer_field(qbank_conn, make_field("yes"), embed=fake_embed)[0].note == "junk label"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_qbank_match.py -q`
Expected: FAIL — `ModuleNotFoundError: career_agent.memory.qbank_match`.

- [ ] **Step 3: Write `src/career_agent/memory/qbank_match.py`**

```python
"""Question-bank retrieval: one page field -> (Match, value).

Faithfulness rule: the LLM may only choose WHICH shortlisted entry a question
is (a letter or NONE). Every value comes from the bank, the profile, the job
row, or a deterministic rule (qbank_rules). Bands:
  CONFIDENT  fill                        exact wording, or clear top match
  LIKELY     fill + flag for review      LLM-picked, polarity or shape doubt
  NONE       leave to rules/judgment/you below FLOOR, LLM said none, no answer
Spec: docs/superpowers/specs/2026-09-26-question-bank-design.md §2."""
from __future__ import annotations

import re
from dataclasses import dataclass, field as _field

import numpy as np

from . import qbank
from .qbank_rules import RULES, RuleCtx, infer_shape, shape_ok

# Starting values — re-derive with `scripts/qbank.py calibrate`.
FLOOR = 0.55          # top score below this = no match (result discarded)
MARGIN = 0.08         # top entry must lead the runner-up by this to skip the LLM
DEFAULT_HIGH = 0.80   # runtime value: agent setting qbank_confident_min / 100

CONFIDENT, LIKELY, NONE = "confident", "likely", "none"

_ESCAPE = re.compile(
    r'''\b(type|enter|write|put|respond with)\b[^"“']{0,20}["“']([^"”']{2,30})["”']''', re.I)
_POLARITY = {"not", "no", "without", "never", "ever", "require", "required", "need"}
_NAME_LIKE = re.compile(r"^[\w.-]+\[")
_OPTION_WORDS = {"yes", "no", "true", "false", "n/a", "na", "-"}
_THINK = re.compile(r"<think>.*?</think>", re.S)
_LETTER = re.compile(r"^\(?([abc])\)?(?:[\s.:)]|$)")


@dataclass
class Match:
    band: str
    entry_id: str | None = None
    score: float = 0.0
    kind: str = "none"                                  # exact | shortlist | llm | none
    candidates: list = _field(default_factory=list)     # [(entry_id, score)] top 3
    escape: str | None = None
    note: str = ""


def split_escape(label: str, description: str = ""):
    """Drop the 'type "X" if …' sentence from the question and return X
    separately. Helper text is scanned for X only, never matched on."""
    escape, kept = None, []
    for s in re.split(r"(?<=[.?!])\s+", (label or "").strip()):
        m = _ESCAPE.search(s)
        if m:
            escape = escape or m.group(2).strip()
        elif s:
            kept.append(s)
    if escape is None:
        m = _ESCAPE.search(description or "")
        escape = m.group(2).strip() if m else None
    return " ".join(kept).strip(), escape


def is_junk(f) -> bool:
    """Not a question: empty/placeholder (perception's own test), a bare option
    word, an input name like cards[uuid][field3], or one of its own options."""
    from ..browser.perception import is_unlabeled
    label = (f.label or "").strip()
    key = qbank.norm(label)
    return (is_unlabeled(f) or key in _OPTION_WORDS or bool(_NAME_LIKE.match(label))
            or key in {qbank.norm(o) for o in (f.options or [])})


def _polarity(text: str) -> set:
    return {t for t in re.findall(r"[a-z]+", (text or "").lower()) if t in _POLARITY}


def llm_pick(question, entry_ids, conn, llm):
    """Which shortlisted entry is this question? The reply must be a letter or
    NONE; anything else counts as NONE (flag, never guess)."""
    if llm is None or not entry_ids:
        return None
    ents = [qbank.get_entry(conn, e) for e in entry_ids[:3]]
    prompt = ("A job application form asks:\n"
              f'"{question}"\n\n'
              "Which ONE of these questions asks exactly the same thing (same meaning, "
              "same yes/no direction)? Reply with the letter only, or NONE if none match.\n\n"
              + "\n".join(f"({'abc'[i]}) {e['question']}" for i, e in enumerate(ents))
              + "\n\nAnswer:")
    try:
        reply = _THINK.sub("", llm(prompt) or "").strip().lower()
    except Exception:
        return None
    m = _LETTER.match(reply)
    if not m:
        return None
    i = "abc".index(m.group(1))
    return ents[i]["id"] if i < len(ents) else None


def match_question(conn, question, *, embed, llm=None, high=DEFAULT_HIGH,
                   floor=FLOOR, margin=MARGIN) -> Match:
    eid = qbank.exact(conn, question)
    if eid:
        return Match(CONFIDENT, eid, 1.0, "exact", [(eid, 1.0)])
    rows = qbank.wordings(conn)
    if not rows or not (question or "").strip():
        return Match(NONE)
    sims = np.stack([v for _, _, v in rows]) @ embed([question])[0]
    best, best_text = {}, {}
    for (text, e, _), s in zip(rows, sims):
        if s > best.get(e, -2.0):
            best[e], best_text[e] = float(s), text
    top = sorted(best.items(), key=lambda kv: -kv[1])[:3]
    cands = [(e, round(s, 3)) for e, s in top]
    s1 = top[0][1]
    s2 = top[1][1] if len(top) > 1 else 0.0
    if s1 < floor:
        return Match(NONE, None, s1, "none", cands, note="below floor")
    if s1 >= high and s1 - s2 >= margin:
        m = Match(CONFIDENT, top[0][0], s1, "shortlist", cands)
    else:
        pick = llm_pick(question, [e for e, s in top if s >= floor], conn, llm)
        if pick is None:
            return Match(NONE, None, s1, "llm", cands,
                         note="llm: none" if llm else "ambiguous, no llm")
        m = Match(LIKELY, pick, best[pick], "llm", cands)
    if _polarity(question) != _polarity(best_text[m.entry_id]):
        m.band, m.note = LIKELY, "polarity differs"
    return m


def resolve_value(conn, entry, *, question, escape, job, contact, _depth=0):
    """Entry -> answer string, or None (unanswered / rule can't decide).
    Precedence: rule > profile_ref > stored answer."""
    if entry.get("rule"):
        fn = RULES.get(entry["rule"])
        if fn is None or _depth > 2:
            return None

        def bank(eid):
            other = qbank.get_entry(conn, eid)
            return None if other is None else resolve_value(
                conn, other, question=other["question"], escape=None,
                job=job, contact=contact, _depth=_depth + 1)
        return fn(RuleCtx(question, entry.get("answer"), escape, job or {}, bank))
    if entry.get("profile_ref"):
        v = (contact or {}).get(entry["profile_ref"])
        return None if v is None or str(v).strip() == "" else str(v).strip()
    a = entry.get("answer")
    return a if a and a.strip() else None


def fit_option(label, value, options, synonyms, llm=None):
    """Canonical value -> one of the page's options, or None (flag). No static
    options (text box, or a combobox whose options load live) -> the value."""
    if not options:
        return value
    by_norm = {qbank.norm(o): o for o in options}
    for cand in [value, *(synonyms or {}).get(value, [])]:
        if qbank.norm(cand) in by_norm:
            return by_norm[qbank.norm(cand)]
    from ..orchestrator.screen_review import _coerce_option
    hit = _coerce_option(value, options)
    if hit is None and llm is not None:
        from ..orchestrator.judgment import match_value_to_option
        hit = match_value_to_option(label, value, options, llm)
    return hit


def answer_field(conn, f, *, embed, llm=None, job=None, contact=None, high=DEFAULT_HIGH):
    if f.kind in ("file", "button") or f.purpose == "attestation":
        return Match(NONE, note="not a bank field"), None
    question, escape = split_escape(f.label, f.description)
    if is_junk(f) or not question:
        return Match(NONE, note="junk label"), None
    m = match_question(conn, question, embed=embed, llm=llm, high=high)
    m.escape = escape
    if m.entry_id is None:
        return m, None
    entry = qbank.get_entry(conn, m.entry_id)
    value = resolve_value(conn, entry, question=question, escape=escape, job=job, contact=contact)
    if value is None:
        m.band, m.note = NONE, "no answer for entry"
        return m, None
    shape = infer_shape(entry["shape"], getattr(f, "input_type", ""),
                        getattr(f, "autocomplete", ""), f.label)
    if not shape_ok(shape, value, escape):
        m.band, m.note = LIKELY, f"shape {shape} failed"
    fitted = fit_option(f.label, value, f.options, entry["synonyms"], llm)
    if fitted is None:
        m.band, m.note = NONE, "no option fits"
    return m, fitted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_qbank_match.py -q`
Expected: 13 passed. If `test_unrelated_question_is_none_but_logs_candidates` fails because the fake embedding's hash collisions push the score over 0.55, print `m.score` and pick an unrelated question with no shared words rather than changing `FLOOR`.

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/memory/qbank_match.py tests/career_agent/test_qbank_match.py
git commit -m "feat(qbank): faithful retrieval — escape split, exact/embedding/LLM-pick bands, polarity+shape gates, option fit"
```

---

### Task 4: Migration + calibration (+ run on the real DB)

**Files:**
- Create: `src/career_agent/memory/qbank_admin.py`
- Create: `scripts/qbank.py`
- Modify: `src/career_agent/memory/qbank_match.py` (FLOOR/MARGIN constants, from calibration output)
- Test: `tests/career_agent/test_qbank_admin.py`

**Interfaces:**
- Consumes: Tasks 1–3; `career_agent.memory.learned_answers.ensure(conn)`; `Field` from `career_agent.browser.form_model`.
- Produces:
  - `migrate_learned(conn, embed) -> {"migrated": [label], "junk": [label], "unmatched": [label]}`
  - `calibrate(conn, embed, negatives=NEGATIVES) -> {"evaluated", "top1_accuracy", "right", "wrong", "negatives", "suggested": {"FLOOR","HIGH","MARGIN"}}`
  - CLI `PYTHONPATH=src python3 scripts/qbank.py {seed|migrate|calibrate} [--db data/jobs.db] [--min-accuracy 0.85]`

- [ ] **Step 1: Write the failing tests**

Create `tests/career_agent/test_qbank_admin.py`:

```python
from career_agent.memory import qbank
from career_agent.memory.learned_answers import ensure as ensure_learned
from career_agent.memory.qbank_admin import calibrate, migrate_learned


def test_migrate_keeps_good_rows_drops_junk(qbank_conn, fake_embed):
    ensure_learned(qbank_conn)
    rows = [("Notice period", "45"), ("Yes", "No"), ("cards[1][field3]", "Linkedin"),
            ("How would you rate your English language skills?", "Fluent"),
            ("Something odd entirely unrelated to anything?", "x")]
    for label, ans in rows:
        qbank_conn.execute("INSERT INTO learned_answers (qkey,label,answer,purpose,updated_at) "
                           "VALUES (?,?,?,NULL,'2026-01-01')", (qbank.norm(label), label, ans))
    r = migrate_learned(qbank_conn, fake_embed)
    assert r["junk"] == ["Yes", "cards[1][field3]"]
    assert r["unmatched"] == ["Something odd entirely unrelated to anything?"]
    assert set(r["migrated"]) == {"Notice period", "How would you rate your English language skills?"}
    assert qbank.get_entry(qbank_conn, "notice_period")["answer"] == "30"          # never overwritten
    assert qbank.get_entry(qbank_conn, "english_proficiency")["answer"] == "Fluent"  # filled when empty


def test_calibrate_reports_accuracy_and_suggestions(qbank_conn, fake_embed):
    r = calibrate(qbank_conn, fake_embed, negatives=["Describe your favourite hobby outside work"])
    assert r["evaluated"] >= 6 and 0 <= r["top1_accuracy"] <= 1
    assert set(r["suggested"]) == {"FLOOR", "HIGH", "MARGIN"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_qbank_admin.py -q`
Expected: FAIL — `ModuleNotFoundError: career_agent.memory.qbank_admin`.

- [ ] **Step 3: Write `src/career_agent/memory/qbank_admin.py`**

```python
"""One-off / maintenance operations on the question bank: pull usable rows out
of the superseded learned_answers table, and measure retrieval so FLOOR /
HIGH / MARGIN come from data instead of guesses (spec §2, §7)."""
from __future__ import annotations

from collections import Counter

import numpy as np

from . import qbank
from .qbank_match import CONFIDENT, is_junk, match_question, split_escape

# Out-of-bank questions: a good FLOOR sits above most of their best scores.
NEGATIVES = [
    "Why do you want to work at our company?",
    "Describe a time you failed and what you learned.",
    "What excites you about our mission?",
    "Have you used our product before? If yes, how?",
    "Tell us about a project you are proud of.",
    "What is your favourite programming language and why?",
    "Describe a disagreement with a teammate and how you resolved it.",
    "What would you build in your first 90 days?",
    "Anything else you would like us to know?",
    "Upload your cover letter",
    "What questions do you have for us?",
    "Describe your ideal manager.",
]


def migrate_learned(conn, embed) -> dict:
    """Move learned_answers rows into the bank. Only CONFIDENT matches migrate
    (no LLM here); an entry's existing answer/rule/profile_ref is never
    overwritten. Junk labels are reported and dropped."""
    from ..browser.form_model import Field
    from .learned_answers import ensure as ensure_learned
    ensure_learned(conn)
    report = {"migrated": [], "junk": [], "unmatched": []}
    for label, answer in conn.execute("SELECT label, answer FROM learned_answers ORDER BY rowid").fetchall():
        f = Field(ref="_migrate", kind="text", label=label or "", required=False)
        question = split_escape(label or "")[0]
        if is_junk(f) or not question:
            report["junk"].append(label)
            continue
        m = match_question(conn, question, embed=embed, llm=None)
        if m.band != CONFIDENT:
            report["unmatched"].append(label)
            continue
        e = qbank.get_entry(conn, m.entry_id)
        qbank.add_wording(conn, question, e["id"], embed([question])[0], "migrated")
        if e["answer"] is None and not e["rule"] and not e["profile_ref"]:
            qbank.set_answer(conn, e["id"], answer)
        report["migrated"].append(label)
    return report


def _pct(xs, p):
    return round(float(np.percentile(xs, p)), 3) if xs else None


def calibrate(conn, embed, negatives=NEGATIVES) -> dict:
    """Hold each wording out, search with it, record whether its own entry comes
    back on top. Suggested: FLOOR = p90 of out-of-bank best scores; HIGH = p95
    of wrong top-1 scores; MARGIN = p10 of the lead correct matches have."""
    rows = qbank.wordings(conn)
    if not rows:
        return {"evaluated": 0, "top1_accuracy": None, "suggested": {"FLOOR": None, "HIGH": None, "MARGIN": None}}
    per_entry = Counter(e for _, e, _ in rows)
    mat = np.stack([v for _, _, v in rows])
    right, wrong, gaps = [], [], []
    for i, (_, e, v) in enumerate(rows):
        if per_entry[e] < 2:
            continue                      # its entry has no other wording to find
        sims = mat @ v
        sims[i] = -2.0
        best: dict = {}
        for (_, e2, _), s in zip(rows, sims):
            best[e2] = max(best.get(e2, -2.0), float(s))
        top = sorted(best.items(), key=lambda kv: -kv[1])
        s2 = top[1][1] if len(top) > 1 else 0.0
        if top[0][0] == e:
            right.append(top[0][1])
            gaps.append(top[0][1] - s2)
        else:
            wrong.append(top[0][1])
    neg = [float((mat @ embed([t])[0]).max()) for t in negatives]
    n = len(right) + len(wrong)
    return {
        "evaluated": n,
        "top1_accuracy": round(len(right) / n, 3) if n else None,
        "right": {"p10": _pct(right, 10), "p50": _pct(right, 50)},
        "wrong": {"p50": _pct(wrong, 50), "p95": _pct(wrong, 95)},
        "negatives": {"p50": _pct(neg, 50), "p90": _pct(neg, 90)},
        "suggested": {"FLOOR": _pct(neg, 90), "HIGH": _pct(wrong, 95), "MARGIN": _pct(gaps, 10)},
    }
```

- [ ] **Step 4: Write `scripts/qbank.py`**

```python
"""Question bank maintenance (spec docs/superpowers/specs/2026-09-26-question-bank-design.md).

  PYTHONPATH=src python3 scripts/qbank.py seed        load/refresh data/qbank_seed.json (answers untouched)
  PYTHONPATH=src python3 scripts/qbank.py migrate     move usable learned_answers rows into the bank
  PYTHONPATH=src python3 scripts/qbank.py calibrate   hold-one-out accuracy + suggested FLOOR/HIGH/MARGIN
                                                      (exit 1 below --min-accuracy: retrieval regression check)
"""
import argparse
import json
import sqlite3
import sys

from career_agent.memory import qbank
from career_agent.memory.qbank_admin import calibrate, migrate_learned


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["seed", "migrate", "calibrate"])
    ap.add_argument("--db", default="data/jobs.db")
    ap.add_argument("--min-accuracy", type=float, default=0.85)
    a = ap.parse_args()
    conn = sqlite3.connect(a.db)
    qbank.ensure(conn)
    embed = qbank.default_embed
    if a.cmd == "seed":
        print(f"seeded {qbank.load_seed(conn, embed)} entries")
    elif a.cmd == "migrate":
        qbank.seed_if_empty(conn, embed)
        print(json.dumps(migrate_learned(conn, embed), indent=2))
    else:
        r = calibrate(conn, embed)
        print(json.dumps(r, indent=2))
        if r["top1_accuracy"] is not None and r["top1_accuracy"] < a.min_accuracy:
            sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_qbank_admin.py -q`
Expected: 2 passed.

- [ ] **Step 6: Run on the real database (back up first)**

```bash
cp data/jobs.db data/backups/jobs-pre-qbank-2026-09-27.db
PYTHONPATH=src python3 scripts/qbank.py seed
PYTHONPATH=src python3 scripts/qbank.py migrate
PYTHONPATH=src python3 scripts/qbank.py calibrate
```

Expected: `seeded 94 entries` (the count of seed entries); migrate report lists `Yes`, `No`, both `cards[…]` rows under `junk`; calibrate prints `top1_accuracy` ≥ 0.85 and a `suggested` block. Record the full calibrate output in the commit message body.

- [ ] **Step 7: Apply calibrated thresholds**

In `src/career_agent/memory/qbank_match.py` set `FLOOR` and `MARGIN` to the suggested values (round to 2 decimals). Rules: if suggested `FLOOR` ≥ `right.p10`, use `right.p10 - 0.02` instead (a floor must not discard most correct matches); if `MARGIN` is `None` or < 0.03, keep 0.08. Note the suggested `HIGH` ×100 (rounded) — Task 5 uses it as the `qbank_confident_min` default; if it's `None` (no wrong matches), use 80.

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_qbank_match.py -q`
Expected: still 13 passed (the tests pass `high=` explicitly where it matters; if a test depends on the old `FLOOR`, pass `floor=0.55` in that test call).

- [ ] **Step 8: Commit**

```bash
git add src/career_agent/memory/qbank_admin.py scripts/qbank.py src/career_agent/memory/qbank_match.py tests/career_agent/test_qbank_admin.py
git commit -m "feat(qbank): learned_answers migration + hold-one-out calibration; thresholds from real-bank run"
```

---

### Task 5: `QBankMemory` adapter, recorder flag, settings

**Files:**
- Create: `src/career_agent/memory/qbank_memory.py`
- Modify: `src/career_agent/orchestrator/qa_recorder.py` (`decision`)
- Modify: `src/job_dashboard/qa_store.py` (`DEFAULT_SETTINGS`, `qbank_confident_min`, `_MEMORY`)
- Test: `tests/career_agent/test_qbank_memory.py`

**Interfaces:**
- Consumes: `answer_field, CONFIDENT, NONE, DEFAULT_HIGH` (Task 3); `FillDecision(ref, kind, label, value, action, source)` and `_action_for_kind(kind)` from `career_agent.orchestrator.mapper`.
- Produces:
  - `QBankMemory(conn, *, embed=None, llm=None, job=None, contact=None, high=DEFAULT_HIGH)` with
    - `recall(fields) -> (list[FillDecision], list[Field])` — source `"qbank"` (confident) or `"qbank_likely"`
    - `explain(field) -> dict` with keys `retrieval_kind, retrieved_qkey, retrieval_score, candidates_json, confidence, basis`
    - `record(field, answer) -> None`, `record_corrections(form, decisions, final_values) -> None` (no-ops)
  - `qa_store.qbank_confident_min(conn) -> int` (0–100, default from calibration, else 80)
  - `QARecorder.decision(d)` records `status="needs_answer"` when `d.source == "qbank_likely"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/career_agent/test_qbank_memory.py`:

```python
from job_dashboard import qa_store
from job_dashboard.db import init_db

from career_agent.memory.qbank_memory import QBankMemory
from career_agent.orchestrator.mapper import FillDecision
from career_agent.orchestrator.qa_recorder import QARecorder


def test_recall_splits_confident_likely_none(qbank_conn, fake_embed, make_field):
    mem = QBankMemory(qbank_conn, embed=fake_embed, job={"location": "Noida"})
    fields = [make_field("Notice period", ref="#n"), make_field("LinkedIn profile URL", ref="#l"),
              make_field("Describe your favourite hobby outside work", ref="#h")]
    ex = mem.explain(fields[0])
    assert (ex["retrieval_kind"], ex["retrieved_qkey"], ex["confidence"]) == ("exact", "notice_period", 100)
    assert ex["candidates_json"][0] == {"tier": "qbank", "qkey": "notice_period", "score": 1.0, "accepted": True}
    decisions, still = mem.recall(fields)
    assert [(d.ref, d.value, d.source, d.action) for d in decisions] == [
        ("#n", "30", "qbank", "fill"), ("#l", "linkedin.com/in/x", "qbank_likely", "fill")]
    assert [f.ref for f in still] == ["#h"]
    assert mem.explain(fields[2])["retrieved_qkey"] is None
    assert mem.record(fields[0], "x") is None and mem.record_corrections([], [], {}) is None


def test_likely_fill_is_recorded_for_review(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    rec = QARecorder(conn, 1, run_key="r")
    rec.decision(FillDecision("#a", "text", "LinkedIn profile URL", "x", "fill", "qbank_likely"))
    rec.decision(FillDecision("#b", "text", "Notice period", "30", "fill", "qbank"))
    assert dict(conn.execute("select ref, status from application_qa")) == {"#a": "needs_answer", "#b": "filled"}
    (q,) = qa_store.open_questions(conn, 1)
    assert (q["label"], q["answer"], q["source"]) == ("LinkedIn profile URL", "x", "qbank_likely")


def test_qbank_setting_default_and_clamp(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    default = qa_store.qbank_confident_min(conn)
    assert 0 < default <= 100
    qa_store.set_setting(conn, "qbank_confident_min", 150)
    assert qa_store.qbank_confident_min(conn) == 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_qbank_memory.py -q`
Expected: FAIL — `ModuleNotFoundError: career_agent.memory.qbank_memory`.

- [ ] **Step 3: Write `src/career_agent/memory/qbank_memory.py`**

```python
"""The question bank behind the interface the fill loop already calls
(recall / record / record_corrections — same as the superseded AnswerMemory),
plus explain() for the QA recorder's retrieval trace.

The bank grows only from choices made on the dashboard (spec §3), so record()
and record_corrections() are deliberately no-ops: run-time answers are kept
per application in application_qa, and read-back edits are logged as
outcome='edited' by the recorder."""
from __future__ import annotations

from ..orchestrator.mapper import FillDecision, _action_for_kind
from . import qbank
from .qbank_match import CONFIDENT, DEFAULT_HIGH, NONE, answer_field


class QBankMemory:
    def __init__(self, conn, *, embed=None, llm=None, job=None, contact=None, high=DEFAULT_HIGH):
        self.conn, self.llm, self.high = conn, llm, high
        self.embed = embed or qbank.default_embed
        self.job, self.contact = job or {}, contact or {}
        qbank.seed_if_empty(conn, self.embed)
        self._cache: dict = {}

    def _answer(self, f):
        # trace_all() runs before recall() on the same fields: compute once
        # (the LLM pick is the expensive part).
        key = (f.ref, f.label, f.description, tuple(f.options or ()))
        if key not in self._cache:
            self._cache[key] = answer_field(self.conn, f, embed=self.embed, llm=self.llm,
                                            job=self.job, contact=self.contact, high=self.high)
        return self._cache[key]

    def explain(self, f) -> dict:
        m, _ = self._answer(f)
        accepted = m.entry_id if m.band != NONE else None
        basis = m.band + (f": {m.note}" if m.note else "") + (f"; escape {m.escape!r}" if m.escape else "")
        return {"retrieval_kind": m.kind, "retrieved_qkey": m.entry_id,
                "retrieval_score": round(m.score, 3),
                "candidates_json": [{"tier": "qbank", "qkey": e, "score": s, "accepted": e == accepted}
                                    for e, s in m.candidates],
                "confidence": int(round(m.score * 100)) if m.entry_id else None,
                "basis": basis}

    def recall(self, fields):
        """(decisions, still_need). Confident -> source 'qbank'; likely ->
        'qbank_likely' (filled, and recorded for review before submit)."""
        decisions, still = [], []
        for f in fields:
            m, value = self._answer(f)
            if m.band == NONE or value is None:
                still.append(f)
                continue
            decisions.append(FillDecision(f.ref, f.kind, f.label, value, _action_for_kind(f.kind),
                                          "qbank" if m.band == CONFIDENT else "qbank_likely"))
        return decisions, still

    def record(self, field, answer):
        return None

    def record_corrections(self, form, decisions, final_values):
        return None
```

- [ ] **Step 4: Flag likely fills in `QARecorder.decision`**

In `src/career_agent/orchestrator/qa_recorder.py` replace:

```python
    def decision(self, d):
        if d.action == "upload":
            return                      # a résumé file path isn't a question
        self._rec(d.ref, d.label, kind=d.kind, answer=str(d.value),
                  source=d.source, status="filled")
```

with:

```python
    def decision(self, d):
        if d.action == "upload":
            return                      # a résumé file path isn't a question
        # A question-bank best guess is on the form but still needs the
        # human's look before submit, so it's listed with the open questions.
        status = "needs_answer" if d.source == "qbank_likely" else "filled"
        self._rec(d.ref, d.label, kind=d.kind, answer=str(d.value),
                  source=d.source, status=status)
```

- [ ] **Step 5: Add the setting and memory sources in `src/job_dashboard/qa_store.py`**

In `DEFAULT_SETTINGS`, add `"qbank_confident_min": "80",` right after `"answer_confidence_min": "60",` — use the calibrated HIGH×100 from Task 4 Step 7 instead of 80 if you recorded one.

Replace `_MEMORY = ("learned", "semantic")      # sources meaning "memory answered this"` with:

```python
_MEMORY = ("learned", "semantic", "qbank", "qbank_likely")   # sources meaning "memory answered this"
```

Add after `confidence_min`:

```python
def qbank_confident_min(conn) -> int:
    """Question-bank match score (0-100) at/above which a clear top match fills
    without a review flag. Separate from answer_confidence_min (LLM drafts)."""
    try:
        return max(0, min(100, int(get_setting(conn, "qbank_confident_min"))))
    except (TypeError, ValueError):
        return int(DEFAULT_SETTINGS["qbank_confident_min"])
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_qbank_memory.py tests/test_qa_api.py -q`
Expected: `test_qbank_memory.py` 3 passed; `test_qa_api.py` unchanged (13 passed).

- [ ] **Step 7: Commit**

```bash
git add src/career_agent/memory/qbank_memory.py src/career_agent/orchestrator/qa_recorder.py src/job_dashboard/qa_store.py tests/career_agent/test_qbank_memory.py
git commit -m "feat(qbank): AnswerMemory-compatible adapter; likely fills listed for review; qbank_confident_min setting"
```

---

### Task 6: Perception captures `input_type` and `autocomplete`

**Files:**
- Modify: `src/career_agent/browser/form_model.py` (`Field`)
- Modify: `src/career_agent/browser/perception.py` (`to_form_model`, `_INPUT_JS` push)
- Test: `tests/career_agent/test_perception_normalize.py`, `tests/career_agent/test_qbank_match.py`

**Interfaces:**
- Produces: `Field.input_type: str = ""`, `Field.autocomplete: str = ""` (lower-case HTML attributes); raw dicts from `_INPUT_JS` carry `input_type`, `autocomplete`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/career_agent/test_perception_normalize.py`:

```python
def test_input_type_and_autocomplete_carried_through():
    raw = [{"ref": "#a", "kind": "text", "label": "Street address", "required": False, "options": [],
            "group": None, "input_type": "text", "autocomplete": "address-line1"},
           {"ref": "#b", "kind": "text", "label": "Notice", "required": False, "options": [], "group": None}]
    a, b = to_form_model(raw)
    assert (a.input_type, a.autocomplete) == ("text", "address-line1")
    assert (b.input_type, b.autocomplete) == ("", "")
```

Append to `tests/career_agent/test_qbank_match.py`:

```python
def test_page_declared_input_type_drives_shape(qbank_conn, fake_embed, make_field):
    m, v = answer_field(qbank_conn, make_field("Notice period", input_type="email"), embed=fake_embed)
    assert (m.band, v) == (LIKELY, "30") and "shape email" in m.note
    m, _ = answer_field(qbank_conn, make_field("Notice period", input_type="number"), embed=fake_embed)
    assert m.band == CONFIDENT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_perception_normalize.py tests/career_agent/test_qbank_match.py -q`
Expected: FAIL — `TypeError: Field.__init__() got an unexpected keyword argument 'input_type'`.

- [ ] **Step 3: Add the fields**

In `src/career_agent/browser/form_model.py`, in `class Field`, after `description: str = ""      # accessible description (aria-describedby helper text)` add:

```python
    input_type: str = ""       # HTML type attribute (email/tel/url/number/date…) — shape clue
    autocomplete: str = ""     # HTML autocomplete token (address-line1, postal-code…) — shape clue
```

In `src/career_agent/browser/perception.py` `to_form_model`, in the first `fields.append(Field(...))` (the non-radio one) add after `description=r.get("description", ""),`:

```python
            input_type=r.get("input_type", ""),
            autocomplete=r.get("autocomplete", ""),
```

In `_INPUT_JS`, in the `out.push({...})` for regular inputs (the one containing `role, haspopup,`), replace `role, haspopup,` with:

```javascript
      role, haspopup,
      input_type: type || '', autocomplete: (el.getAttribute('autocomplete') || '').toLowerCase(),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent -q`
Expected: all pass (previous count + new tests). With `RUN_BROWSER_TESTS=1` also run `tests/career_agent/test_perception_browser.py` to confirm the JS still evaluates.

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/browser/form_model.py src/career_agent/browser/perception.py tests/career_agent/test_perception_normalize.py tests/career_agent/test_qbank_match.py
git commit -m "feat(perception): capture input type + autocomplete as shape clues for the question bank"
```

---

### Task 7: Wire the bank into the run

**Files:**
- Modify: `src/career_agent/apply.py:189-212`
- Modify: `src/career_agent/orchestrator/graph.py` (`_semantic_split`, `fill_node`, `human_gate_node`)
- Test: full suite + dry run on a fixture

**Interfaces:**
- Consumes: `QBankMemory` (Task 5), `qa_store.qbank_confident_min` (Task 5), `job_dashboard.db.get_job(conn, id)`, `job_dashboard.letter.draft.make_default_llm()`.

- [ ] **Step 1: Replace the learning-loop setup in `apply.py`**

Replace:

```python
    # Learning loop (Phase D): reuse answers the human typed on past forms
    # before escalating again; record new ones. Same jobs.db, no new store.
    from .memory.learned_answers import AnswerMemory
    learn = AnswerMemory(conn)
```

with:

```python
    # Question bank (spec 2026-09-26): canonical questions answered once on the
    # dashboard. The LLM only picks which entry a question is — never the value.
    from .memory.qbank_memory import QBankMemory
    from job_dashboard.db import get_job
    _qllm = None
    if not args.no_llm:
        try:
            from job_dashboard.letter.draft import make_default_llm
            _qllm = make_default_llm()
        except Exception as e:
            print(f"[warn] qbank LLM pick unavailable ({type(e).__name__}: {e})")
    learn = QBankMemory(conn, llm=_qllm, contact=contact,
                        job=(get_job(conn, args.job_id) if args.job_id else None) or {},
                        high=qa_store.qbank_confident_min(conn) / 100)
```

Replace:

```python
    from .memory.retrieval_trace import explain as _explain
    qa_rec.tracer = lambda f: _explain(conn, _qa_vault, f)
```

with:

```python
    qa_rec.tracer = learn.explain
```

(The `memory_router` block between them stays: the MCP server tools still use it.)

- [ ] **Step 2: Remove the semantic tier from `graph.py`**

Delete the whole `def _semantic_split(fields, mem_router):` function (through its `return auto, rest`).

In `fill_node` replace:

```python
    recalled, remaining = [], fillable
    if learn:
        recalled, remaining = learn.recall(fillable)

    # Tri-Partite Memory: autonomous semantic answers bypass the human gate.
    mem_router = c.get("memory_router")
    auto_semantic, remaining = _semantic_split(remaining, mem_router)

    from ..orchestrator.screen_review import map_screen
    decisions, needs = map_screen(remaining, profile, resume_pdf)
    decisions += recalled + auto_semantic
```

with:

```python
    # Question bank first (confident fills + flagged best guesses); whatever it
    # can't answer falls through to rules/profile, then judgment.
    recalled, remaining = [], fillable
    if learn:
        recalled, remaining = learn.recall(fillable)

    from ..orchestrator.screen_review import map_screen
    decisions, needs = map_screen(remaining, profile, resume_pdf)
    decisions += recalled
```

In `human_gate_node` delete the block from `    mem_router = c.get("memory_router")` through `            learn.record(f, ans)` (the RECORD_FEEDBACK dual-write loop and its `events` lookup) and put in its place:

```python
    # Human answers are kept per application (qa.answered above); they join the
    # question bank only when promoted on the dashboard (spec §3).
```

Then, if `learn` is no longer referenced anywhere in `human_gate_node`, delete its `learn = c.get("learn")` line (graph.py:417).

- [ ] **Step 3: Run the full suite**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent tests/test_qa_api.py -q`
Expected: all pass. A failure naming `_semantic_split` or `RECORD_FEEDBACK` in a graph test means that test asserted the removed tier — update it to assert `learn.recall` decisions instead.

- [ ] **Step 4: Dry run against a local fixture**

```bash
PYTHONPATH=src python3 -m career_agent.apply --url "file://$PWD/tests/career_agent/fixtures/greenhouse_labels.html" --no-llm
```

Expected: run completes with `reached_submit_dry_run` or a human-gate stop, and no traceback. Then:

```bash
sqlite3 data/jobs.db "select label, source, status, retrieval_kind, retrieved_qkey, retrieval_score from application_qa order by id desc limit 15"
```

Expected: rows with `source` `qbank`/`qbank_likely` for questions the bank knows and answers you've entered (unanswered entries show `status=needs_answer`, `retrieval_kind` set). Paste this output into the commit message body.

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/apply.py src/career_agent/orchestrator/graph.py
git commit -m "feat(agent): question bank replaces learned_answers + semantic vault in the fill loop"
```

---

### Task 8: Questionnaire API

**Files:**
- Modify: `src/job_dashboard/api/qa_routes.py` (answers/reply/review/settings routes; new entries route)
- Modify: `src/job_dashboard/api/app.py:30,78` (`qa_vault` → `qa_embed`)
- Modify: `src/job_dashboard/qa_store.py` (`retrieval_stats` → `by_band`)
- Test: `tests/test_qa_api.py` (rewrite answer/reply/review tests)

**Interfaces:**
- Consumes: `qbank.*`, `split_escape`, `NO_INPUT_RULES`, `RULE_HELP`, `job_dashboard.apply.store.get_application_profile(conn)`.
- Produces (HTTP):
  - `GET /api/answers?q=` → `{"answers": [{id, question, topic, atype, answer, profile_ref, rule, rule_help, value, needs_input, wordings, asked_in, updated_at}], "unanswered": int}`
  - `PUT /api/answers` body `{answer, entry_id?}` or `{answer, question}` → `{"ok": true, "id"}`; 404 unknown entry; 422 blank/neither
  - `DELETE /api/answers?entry_id=` → supersede; 404 unknown
  - `GET /api/qbank/entries?search=` → `{"entries": [{id, question, topic}]}`
  - `GET /api/jobs/{id}/questions` → rows now include `asked_in`
  - `POST /api/jobs/{id}/questions/{row}/reply` body `{answer, save_as: "once"|"new"|"wording", entry_id?}`
  - `POST /api/application-qa/{row}/review` body `{verdict: "correct"|"wrong", entry_id?}`
  - `GET/PUT /api/agent-settings` include `qbank_confident_min`
  - `GET /api/retrieval/stats` adds `by_band: [{band, kept, edited, edit_rate}]`
  - `create_app(..., qa_embed=None)`

- [ ] **Step 1: Rewrite the tests**

In `tests/test_qa_api.py` delete `FakeVault`, `BrokenVault`, the `env` fixture, `_learned`, and these tests: `test_short_answer_is_written_to_both_stores_and_listed_merged`, `test_essay_goes_to_vault_only`, `test_delete_removes_both_and_404s_when_absent`, `test_reply_teaches_memory_and_closes_question`, `test_textarea_reply_is_vault_only`, `test_vault_down_still_lists_learned_answers`, `_seed_filled`, `test_review_wrong_with_fix_teaches_memory_and_marks_edited`, `test_review_correct_marks_kept_without_touching_memory`, `test_review_validation`, `test_recent_and_empty_stats`, `test_settings_default_update_and_bounds`. Keep `test_reply_404_and_blank_422` and `test_ingredients_missing_file_is_empty`. Add after the imports:

```python
@pytest.fixture
def env(tmp_path, fake_embed):
    db = str(tmp_path / "t.db")
    c = init_db(db)
    insert_job(c, JobListing(source="s", title="ML Eng", company="Acme",
                             job_url="https://x/1", description="jd"))
    c.close()
    return TestClient(create_app(db_path=db, qa_embed=fake_embed)), db


def _entry(c, eid):
    return next(a for a in c.get("/api/answers").json()["answers"] if a["id"] == eid)


def _open(db, label="Have you used Claude before?", kind="radio_group"):
    conn = init_db(db)
    qa_store.record(conn, job_id=1, run_key="r", ref=label, label=label, kind=kind, status="needs_answer")
    rid = conn.execute("select max(id) from application_qa").fetchone()[0]
    conn.close()
    return rid


def _filled(db, label="How many days is your notice?", matched="notice_period", kind="shortlist"):
    conn = init_db(db)
    qa_store.record(conn, job_id=1, run_key="r", ref="#a", label=label, kind="text", status="filled",
                    answer="30", source="qbank", retrieval_kind=kind, retrieved_qkey=matched,
                    retrieval_score=0.72)
    rid = conn.execute("select max(id) from application_qa").fetchone()[0]
    conn.close()
    return rid


def test_questionnaire_lists_seed_with_unanswered_count(env):
    c, _ = env
    body = c.get("/api/answers").json()
    assert len(body["answers"]) >= 90 and body["unanswered"] > 0
    n = _entry(c, "notice_period")
    assert n["needs_input"] is False and "Notice period" in n["wordings"]
    s = _entry(c, "sponsorship_required")
    assert s["needs_input"] is True and s["value"] is None
    w = _entry(c, "work_location")
    assert w["needs_input"] is False and "relocating" in w["rule_help"]
    assert any(a["id"] == "sponsorship_required" for a in c.get("/api/answers?q=sponsor").json()["answers"])


def test_answer_entry_and_add_new(env):
    c, _ = env
    before = c.get("/api/answers").json()["unanswered"]
    assert c.put("/api/answers", json={"entry_id": "sponsorship_required", "answer": "Yes"}).status_code == 200
    assert _entry(c, "sponsorship_required")["value"] == "Yes"
    assert c.get("/api/answers").json()["unanswered"] == before - 1
    assert c.put("/api/answers", json={"question": "Have you used Claude?", "answer": "Yes"}).json()["id"] == "have_you_used_claude"
    assert c.put("/api/answers", json={"entry_id": "nope", "answer": "x"}).status_code == 404
    assert c.put("/api/answers", json={"answer": "x"}).status_code == 422
    assert c.put("/api/answers", json={"entry_id": "pronouns", "answer": " "}).status_code == 422


def test_delete_supersedes_not_erases(env):
    c, db = env
    assert c.delete("/api/answers", params={"entry_id": "pronouns"}).status_code == 200
    assert all(a["id"] != "pronouns" for a in c.get("/api/answers").json()["answers"])
    conn = init_db(db)
    assert conn.execute("select status from qbank_entry where id='pronouns'").fetchone() == ("superseded",)
    conn.close()
    assert c.delete("/api/answers", params={"entry_id": "nope"}).status_code == 404


def test_entries_search(env):
    c, _ = env
    ids = [e["id"] for e in c.get("/api/qbank/entries?search=notice").json()["entries"]]
    assert "notice_period" in ids and "gender" not in ids


def test_reply_once_closes_without_touching_bank(env):
    c, db = env
    rid = _open(db)
    n = len(c.get("/api/answers").json()["answers"])
    assert c.get("/api/jobs/1/questions").json()["questions"][0]["asked_in"] == 1
    assert c.post(f"/api/jobs/1/questions/{rid}/reply", json={"answer": "Yes"}).status_code == 200
    assert c.get("/api/jobs/1/questions").json()["questions"] == []
    assert len(c.get("/api/answers").json()["answers"]) == n


def test_reply_new_creates_entry(env):
    c, db = env
    rid = _open(db)
    assert c.post(f"/api/jobs/1/questions/{rid}/reply", json={"answer": "Yes", "save_as": "new"}).status_code == 200
    e = _entry(c, "have_you_used_claude_before")
    assert (e["value"], e["atype"]) == ("Yes", "choice")


def test_reply_wording_attaches_and_validates(env):
    c, db = env
    label = "Do you require a work visa sponsorship now or later?"
    rid = _open(db, label, "select")
    url = f"/api/jobs/1/questions/{rid}/reply"
    assert c.post(url, json={"answer": "Yes", "save_as": "wording"}).status_code == 422
    assert c.post(url, json={"answer": "Yes", "save_as": "bogus"}).status_code == 422
    assert c.post(url, json={"answer": "Yes", "save_as": "wording", "entry_id": "sponsorship_required"}).status_code == 200
    assert label in _entry(c, "sponsorship_required")["wordings"]


def test_review_correct_learns_the_wording_and_bands(env):
    c, db = env
    rid = _filled(db)
    assert c.post(f"/api/application-qa/{rid}/review", json={"verdict": "correct"}).status_code == 200
    assert "How many days is your notice?" in _entry(c, "notice_period")["wordings"]
    stats = c.get("/api/retrieval/stats").json()
    assert stats["reviewed"]["kept"] == 1
    assert stats["by_band"] == [{"band": "0.7–0.8", "kept": 1, "edited": 0, "edit_rate": 0.0}]


def test_review_wrong_repoints_to_the_right_entry(env):
    c, db = env
    rid = _filled(db, label="When does your current job end?")
    assert c.post(f"/api/application-qa/{rid}/review",
                  json={"verdict": "wrong", "entry_id": "last_working_day"}).status_code == 200
    assert "When does your current job end?" in _entry(c, "last_working_day")["wordings"]
    assert "When does your current job end?" not in _entry(c, "notice_period")["wordings"]
    stats = c.get("/api/retrieval/stats").json()
    assert stats["reviewed"]["edited"] == 1 and stats["top_wrong_entries"][0]["qkey"] == "notice_period"


def test_review_validation(env):
    c, db = env
    assert c.post("/api/application-qa/1/review", json={"verdict": "meh"}).status_code == 422
    assert c.post("/api/application-qa/99/review", json={"verdict": "correct"}).status_code == 404
    rid = _filled(db)
    assert c.post(f"/api/application-qa/{rid}/review", json={"verdict": "wrong", "entry_id": "nope"}).status_code == 422


def test_settings_include_qbank_threshold(env):
    c, _ = env
    s = c.get("/api/agent-settings").json()
    assert s["answer_confidence_min"] == 60 and 0 < s["qbank_confident_min"] <= 100
    assert c.put("/api/agent-settings", json={"qbank_confident_min": 85}).status_code == 200
    assert c.get("/api/agent-settings").json()["qbank_confident_min"] == 85
    assert c.put("/api/agent-settings", json={"qbank_confident_min": 101}).status_code == 422


def test_recent_and_empty_stats(env):
    c, db = env
    assert c.get("/api/retrieval/stats").json()["total_fields"] == 0
    _filled(db)
    (r,) = c.get("/api/retrieval/recent").json()["recent"]
    assert (r["label"], r["retrieval_kind"], r["title"]) == ("How many days is your notice?", "shortlist", "ML Eng")
```

Update the kept `test_reply_404_and_blank_422` and `test_ingredients_missing_file_is_empty` to unpack `c, _ = env` (the fixture now returns two values).

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/test_qa_api.py -q`
Expected: FAIL — `TypeError: create_app() got an unexpected keyword argument 'qa_embed'`.

- [ ] **Step 3: `app.py` — swap the injectable**

In `src/job_dashboard/api/app.py` change the `create_app` parameter `qa_vault=None` to `qa_embed=None`, and `app.include_router(build_qa_router(db_path, qa_vault))` to `app.include_router(build_qa_router(db_path, qa_embed))`.

- [ ] **Step 4: `qa_store.retrieval_stats` — add `by_band`**

In `retrieval_stats`, before `return {`, add:

```python
    bands = q("""SELECT MIN(CAST(retrieval_score * 10 AS INT), 9), SUM(outcome='kept'), SUM(outcome='edited')
                 FROM application_qa WHERE source IN ('qbank', 'qbank_likely')
                 AND retrieval_score IS NOT NULL AND outcome IS NOT NULL GROUP BY 1 ORDER BY 1""")
```

and add this key to the returned dict (after `"top_wrong_entries": …,`):

```python
        "by_band": [{"band": f"{b / 10:.1f}–{(b + 1) / 10:.1f}", "kept": k or 0, "edited": e or 0,
                     "edit_rate": round((e or 0) / ((k or 0) + (e or 0)), 3)} for b, k, e in bands],
```

- [ ] **Step 5: Rewrite the answer routes in `qa_routes.py`**

Replace the module docstring, the `_SHORT` constant, `AnswerBody`, `ReplyBody`, `ReviewBody`, and everything in `build_qa_router` from its `def` line through the end of `answer_applications` with the code below; then replace the `reply` and `review` route functions with the versions below; then update the two settings routes. Keep `job_questions`… `answers_used`, `retrieval_*`, `ingredients` otherwise unchanged (except `job_questions`, replaced below).

```python
"""Questionnaire (question bank) + per-application questions API.

The questionnaire is the agent's question bank (career_agent.memory.qbank):
one entry per canonical question, answered once here. Per-application rows
come from application_qa. The bank grows only from choices made here: a reply
becomes a new entry, another wording of an entry, or stays one-off; a review
confirms a wording or re-points it to the right entry. Spec 2026-09-26 §3–4.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from career_agent.memory import qbank
from career_agent.memory.qbank_match import split_escape
from career_agent.memory.qbank_rules import NO_INPUT_RULES, RULE_HELP
from job_dashboard import qa_store
from job_dashboard.apply.store import get_application_profile
from job_dashboard.db import init_db
from job_dashboard.sources.cdp import state as cdp_state


class AnswerBody(BaseModel):
    answer: str
    entry_id: Optional[str] = None     # answer an existing entry
    question: Optional[str] = None     # or create a new one


class ReplyBody(BaseModel):
    answer: str
    save_as: str = "once"              # "once" | "new" | "wording"
    entry_id: Optional[str] = None     # required for "wording"


class ReviewBody(BaseModel):
    verdict: str                       # "correct" | "wrong"
    entry_id: Optional[str] = None     # wrong: the entry this question really is


class SettingsBody(BaseModel):
    answer_confidence_min: Optional[int] = None
    qbank_confident_min: Optional[int] = None
    browser_linkedin_enabled: Optional[bool] = None
    browser_naukri_enabled: Optional[bool] = None
    browser_wellfound_enabled: Optional[bool] = None
    browser_instahyre_enabled: Optional[bool] = None
    browser_iimjobs_enabled: Optional[bool] = None
    browser_indeed_enabled: Optional[bool] = None


BROWSER_SITES = ("linkedin", "naukri", "wellfound", "instahyre", "iimjobs", "indeed")


def _browser_flags(conn) -> dict:
    return {f"browser_{s}_enabled": qa_store.get_setting(conn, f"browser_{s}_enabled") == "1" for s in BROWSER_SITES}


def build_qa_router(db_path, embed=None) -> APIRouter:
    router = APIRouter()

    def get_embed():
        return embed or qbank.default_embed

    def db():
        conn = init_db(db_path)
        qa_store.ensure(conn)
        qbank.seed_if_empty(conn, get_embed())
        return conn

    def view(conn, e, asked, profile) -> dict:
        words = qbank.wordings_for(conn, e["id"])
        raw = profile.get(e["profile_ref"]) if e["profile_ref"] else e["answer"]
        value = None if raw is None or str(raw).strip() == "" else str(raw)
        return {"id": e["id"], "question": e["question"], "topic": e["topic"], "atype": e["atype"],
                "answer": e["answer"], "profile_ref": e["profile_ref"], "rule": e["rule"],
                "rule_help": RULE_HELP.get(e["rule"]), "value": value,
                "needs_input": not e["profile_ref"] and e["rule"] not in NO_INPUT_RULES,
                "wordings": words, "updated_at": e["updated_at"],
                "asked_in": sum(asked.get(qa_store.norm_key(w), 0) for w in words)}

    def link(conn, label, entry_id, source, replace):
        q = split_escape(label)[0] or label
        qbank.add_wording(conn, q, entry_id, get_embed()([q])[0], source, replace=replace)

    @router.get("/api/answers")
    def list_answers(q: str = ""):
        conn = db()
        try:
            asked = qa_store.asked_in_counts(conn)
            profile = get_application_profile(conn) or {}
            out = [view(conn, e, asked, profile) for e in qbank.entries(conn)]
        finally:
            conn.close()
        needle = q.strip().lower()
        if needle:
            out = [a for a in out if needle in a["question"].lower() or needle in (a["value"] or "").lower()
                   or any(needle in w.lower() for w in a["wordings"])]
        return {"answers": out,
                "unanswered": sum(1 for a in out if a["needs_input"] and a["value"] is None)}

    @router.put("/api/answers")
    def upsert_answer(body: AnswerBody):
        ans = body.answer.strip()
        if not ans:
            raise HTTPException(status_code=422, detail="answer is required")
        conn = db()
        try:
            if body.entry_id:
                if not qbank.set_answer(conn, body.entry_id, ans):
                    raise HTTPException(status_code=404, detail="no such entry")
                eid = body.entry_id
            elif (body.question or "").strip():
                eid = qbank.add_entry(conn, question=body.question.strip(), kind="text",
                                      answer=ans, embed=get_embed())
            else:
                raise HTTPException(status_code=422, detail="entry_id or question is required")
        finally:
            conn.close()
        return {"ok": True, "id": eid}

    @router.delete("/api/answers")
    def delete_answer(entry_id: str):
        """Retire, don't erase: the entry stays in the DB as superseded."""
        conn = db()
        try:
            if not qbank.set_status(conn, entry_id, "superseded"):
                raise HTTPException(status_code=404, detail="no such entry")
        finally:
            conn.close()
        return {"ok": True}

    @router.get("/api/qbank/entries")
    def qbank_entries(search: str = ""):
        conn = db()
        try:
            n = search.strip().lower()
            return {"entries": [{"id": e["id"], "question": e["question"], "topic": e["topic"]}
                                for e in qbank.entries(conn)
                                if not n or n in e["question"].lower() or n in e["id"]]}
        finally:
            conn.close()

    @router.get("/api/answers/applications")
    def answer_applications(qkey: str):
        conn = db()
        try:
            return {"applications": qa_store.applications_for(conn, qkey)}
        finally:
            conn.close()
```

Replace `job_questions`:

```python
    @router.get("/api/jobs/{job_id}/questions")
    def job_questions(job_id: int):
        conn = db()
        try:
            asked = qa_store.asked_in_counts(conn)
            return {"questions": [dict(q, asked_in=asked.get(q["qkey"], 0))
                                  for q in qa_store.open_questions(conn, job_id)]}
        finally:
            conn.close()
```

Replace `reply`:

```python
    @router.post("/api/jobs/{job_id}/questions/{row_id}/reply")
    def reply(job_id: int, row_id: int, body: ReplyBody):
        ans = body.answer.strip()
        if not ans:
            raise HTTPException(status_code=422, detail="answer is required")
        if body.save_as not in ("once", "new", "wording"):
            raise HTTPException(status_code=422, detail="save_as must be once, new or wording")
        conn = db()
        try:
            row = conn.execute("SELECT label, kind FROM application_qa WHERE id=? AND job_id=?",
                               (row_id, job_id)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="question not found")
            label, kind = row
            if body.save_as == "new":
                qbank.add_entry(conn, question=split_escape(label)[0] or label, kind=kind,
                                answer=ans, embed=get_embed())
            elif body.save_as == "wording":
                if not body.entry_id or qbank.get_entry(conn, body.entry_id) is None:
                    raise HTTPException(status_code=422, detail="pick an existing entry")
                link(conn, label, body.entry_id, "human", replace=True)
            qa_store.mark_answered(conn, job_id, qa_store.norm_key(label), ans)
        finally:
            conn.close()
        return {"ok": True}
```

Replace `review`:

```python
    @router.post("/api/application-qa/{row_id}/review")
    def review(row_id: int, body: ReviewBody):
        """Correct: a similar-wording match becomes an exact wording of its entry.
        Wrong + entry_id: this wording is re-pointed to the entry it really is."""
        if body.verdict not in ("correct", "wrong"):
            raise HTTPException(status_code=422, detail="verdict must be correct or wrong")
        conn = db()
        try:
            row = conn.execute("SELECT label, retrieved_qkey, retrieval_kind FROM application_qa WHERE id=?",
                               (row_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="not found")
            label, matched, kind = row
            if body.verdict == "correct":
                if matched and kind in ("shortlist", "llm") and qbank.get_entry(conn, matched):
                    link(conn, label, matched, "kept", replace=False)
            elif body.entry_id:
                if qbank.get_entry(conn, body.entry_id) is None:
                    raise HTTPException(status_code=422, detail="no such entry")
                link(conn, label, body.entry_id, "human", replace=True)
            qa_store.set_outcome(conn, row_id, "kept" if body.verdict == "correct" else "edited")
        finally:
            conn.close()
        return {"ok": True}
```

Replace the two settings routes:

```python
    @router.get("/api/agent-settings")
    def get_settings():
        conn = db()
        try:
            return {"answer_confidence_min": qa_store.confidence_min(conn),
                    "qbank_confident_min": qa_store.qbank_confident_min(conn),
                    **_browser_flags(conn),
                    "browser_min_interval_hours": cdp_state.interval_hours(conn)}
        finally:
            conn.close()

    @router.put("/api/agent-settings")
    def put_settings(body: SettingsBody):
        for key in ("answer_confidence_min", "qbank_confident_min"):
            v = getattr(body, key)
            if v is not None and not 0 <= v <= 100:
                raise HTTPException(status_code=422, detail=f"{key} must be 0-100")
        conn = db()
        try:
            for key in ("answer_confidence_min", "qbank_confident_min"):
                if getattr(body, key) is not None:
                    qa_store.set_setting(conn, key, getattr(body, key))
            for site in BROWSER_SITES:
                val = getattr(body, f"browser_{site}_enabled")
                if val is not None:
                    qa_store.set_setting(conn, f"browser_{site}_enabled", "1" if val else "0")
            return {"answer_confidence_min": qa_store.confidence_min(conn),
                    "qbank_confident_min": qa_store.qbank_confident_min(conn),
                    **_browser_flags(conn)}
        finally:
            conn.close()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/test_qa_api.py tests/career_agent -q`
Expected: all pass. Also run `PYTHONPATH=src python3 -m pytest tests -q -x` and fix any other caller of `create_app(..., qa_vault=...)` (grep: `grep -rn "qa_vault" src tests`) by switching it to `qa_embed`.

- [ ] **Step 7: Commit**

```bash
git add src/job_dashboard/api/qa_routes.py src/job_dashboard/api/app.py src/job_dashboard/qa_store.py tests/test_qa_api.py
git commit -m "feat(api): questionnaire endpoints on the question bank — answer, save-as, re-point, by-band stats"
```

---

### Task 9: Dashboard screens

**Files:**
- Modify: `frontend/src/api.js:175-198`
- Create: `frontend/src/components/EntryPicker.jsx`
- Modify: `frontend/src/components/AnswersTab.jsx` (rewrite), `QuestionsPanel.jsx`, `AnswersUsed.jsx`, `RetrievalPanel.jsx`
- Test: `frontend/src/__tests__/answers_tab.test.jsx` (rewrite), `answers_used.test.jsx`, `retrieval_panel.test.jsx`, `tracker_board.test.jsx`

**Interfaces:**
- Consumes: the Task 8 HTTP API.
- Produces (api.js): `fetchAnswers(q) -> {answers, unanswered}`, `saveAnswer(body)`, `deleteAnswer(entryId)`, `fetchQbankEntries(search) -> [{id, question, topic}]`, `replyQuestion(jobId, rowId, answer, save_as="once", entry_id=null)`, `reviewAnswer(rowId, verdict, entry_id=null)`, `saveAgentSettings(numberOrBody)`.
- Produces (component): `<EntryPicker id label onChange={(entryId|null) => …} />`.

- [ ] **Step 1: Update `frontend/src/api.js`**

Replace lines from `export const fetchAnswers` through `export const saveAgentSettings = …` (the two-line definition) and the `reviewAnswer` definition with:

```javascript
export const fetchAnswers = (q = "") =>
  fetch(`/api/answers?q=${encodeURIComponent(q)}`).then(json);          // {answers, unanswered}
export const saveAnswer = (body) => fetch("/api/answers", jsonBody("PUT", body)).then(json);
export const deleteAnswer = (entryId) =>
  fetch(`/api/answers?entry_id=${encodeURIComponent(entryId)}`, { method: "DELETE" }).then(json);
export const fetchQbankEntries = (search = "") =>
  fetch(`/api/qbank/entries?search=${encodeURIComponent(search)}`).then(json).then((d) => d.entries || []);
export const fetchAnswerApps = (qkey) =>
  fetch(`/api/answers/applications?qkey=${encodeURIComponent(qkey)}`).then(json).then((d) => d.applications || []);
export const fetchJobQuestions = (id) =>
  fetch(`/api/jobs/${id}/questions`).then(json).then((d) => d.questions || []);
export const fetchOpenCounts = () => fetch("/api/questions/open-counts").then(json);
export const replyQuestion = (jobId, rowId, answer, save_as = "once", entry_id = null) =>
  fetch(`/api/jobs/${jobId}/questions/${rowId}/reply`, jsonBody("POST", { answer, save_as, entry_id })).then(json);
export const fetchAgentSettings = () => fetch("/api/agent-settings").then(json);
export const saveAgentSettings = (body) =>
  fetch("/api/agent-settings", jsonBody("PUT", typeof body === "number" ? { answer_confidence_min: body } : body)).then(json);
```

and

```javascript
export const reviewAnswer = (rowId, verdict, entry_id = null) =>
  fetch(`/api/application-qa/${rowId}/review`, jsonBody("POST", { verdict, entry_id })).then(json);
```

- [ ] **Step 2: Create `frontend/src/components/EntryPicker.jsx`**

```jsx
import React, { useEffect, useState } from "react";
import { fetchQbankEntries } from "../api.js";

const INPUT = { fontSize: 12, padding: "6px 10px", border: "0.5px solid var(--hairline)", borderRadius: 8, background: "var(--canvas)", color: "var(--ink)", width: "100%", boxSizing: "border-box" };

// Pick a questionnaire entry by typing (native <datalist> over the bank).
// onChange receives the entry id once the text matches an entry, else null.
export default function EntryPicker({ id, label, onChange }) {
  const [entries, setEntries] = useState([]);
  const [text, setText] = useState("");
  useEffect(() => { fetchQbankEntries().then(setEntries).catch(() => setEntries([])); }, []);
  const pick = (v) => {
    setText(v);
    const hit = entries.find((e) => e.question === v || e.id === v);
    onChange(hit ? hit.id : null);
  };
  return (
    <>
      <input aria-label={label} list={`${id}-list`} value={text} placeholder="Type to find the question…"
             onChange={(e) => pick(e.target.value)} style={INPUT} />
      <datalist id={`${id}-list`}>
        {entries.map((e) => <option key={e.id} value={e.question} />)}
      </datalist>
    </>
  );
}
```

- [ ] **Step 3: Write the failing frontend tests**

Replace `frontend/src/__tests__/answers_tab.test.jsx` with:

```jsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import AnswersTab from "../components/AnswersTab.jsx";

const DATA = { unanswered: 1, answers: [
  { id: "sponsorship_required", question: "Will you require visa sponsorship?", topic: "work_auth", atype: "bool",
    answer: null, profile_ref: null, rule: null, rule_help: null, value: null, needs_input: true,
    wordings: ["Will you require visa sponsorship?"], asked_in: 2 },
  { id: "gender", question: "What is your gender?", topic: "demographics", atype: "choice", answer: null,
    profile_ref: "gender", rule: null, rule_help: null, value: "Male", needs_input: false, wordings: ["Gender"], asked_in: 0 },
  { id: "interviewed_before", question: "Have you interviewed with this company before?", topic: "background",
    atype: "bool", answer: "none", profile_ref: null, rule: "company_in_list",
    rule_help: "Companies where the answer is Yes, comma-separated — or 'none'.", value: "none",
    needs_input: true, wordings: [], asked_in: 0 },
]};

function mock() {
  const calls = [];
  global.fetch = vi.fn((url, opts) => {
    const u = String(url);
    calls.push([u, opts]);
    const ok = (b) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(b) });
    if (u.includes("/api/agent-settings")) return ok({ answer_confidence_min: 60, qbank_confident_min: 80 });
    if (u.includes("/api/ingredients")) return ok({ units: [], skills_pool: [] });
    if (u.includes("/api/retrieval")) return ok({ total_fields: 0 });
    if (u.includes("/api/answers")) return ok(opts && opts.method ? { ok: true } : DATA);
    return ok({});
  });
  return calls;
}

beforeEach(() => { vi.restoreAllMocks(); });

test("groups by topic, shows unanswered count, profile values and rule help", async () => {
  mock();
  render(<AnswersTab />);
  expect(await screen.findByText("1 unanswered")).toBeInTheDocument();
  expect(screen.getByText("Work authorization")).toBeInTheDocument();
  expect(screen.getByText(/from your profile \(gender\)/)).toBeInTheDocument();
  expect(screen.getByText("Male")).toBeInTheDocument();
  expect(screen.getByText(/comma-separated/)).toBeInTheDocument();
  expect(screen.getByText(/asked in 2 applications/)).toBeInTheDocument();
});

test("answering a yes/no entry PUTs entry_id and answer", async () => {
  const calls = mock();
  render(<AnswersTab />);
  fireEvent.change(await screen.findByLabelText("Answer for Will you require visa sponsorship?"), { target: { value: "Yes" } });
  fireEvent.click(screen.getByRole("button", { name: "Save Will you require visa sponsorship?" }));
  await waitFor(() => {
    const put = calls.find(([u, o]) => u.includes("/api/answers") && o && o.method === "PUT");
    expect(JSON.parse(put[1].body)).toEqual({ entry_id: "sponsorship_required", answer: "Yes" });
  });
});

test("only-unanswered hides answered and profile entries", async () => {
  mock();
  render(<AnswersTab />);
  await screen.findByText("What is your gender?");
  fireEvent.click(screen.getByLabelText("Only unanswered"));
  expect(screen.queryByText("What is your gender?")).toBeNull();
  expect(screen.queryByText("Have you interviewed with this company before?")).toBeNull();
  expect(screen.getByText("Will you require visa sponsorship?")).toBeInTheDocument();
});

test("remove asks first, then DELETEs by entry id", async () => {
  const calls = mock();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<AnswersTab />);
  await screen.findByText("What is your gender?");
  fireEvent.click(screen.getByRole("button", { name: "Remove What is your gender?" }));
  await waitFor(() => expect(calls.some(([u, o]) => o && o.method === "DELETE" && u.includes("entry_id=gender"))).toBe(true));
});

test("both thresholds are editable", async () => {
  mock();
  render(<AnswersTab />);
  expect((await screen.findByLabelText(/Minimum match score/)).value).toBe("80");
  expect(screen.getByLabelText(/Minimum confidence to fill a generated answer/).value).toBe("60");
});
```

In `frontend/src/__tests__/answers_used.test.jsx`: in `mock`, before the final `return`, add

```javascript
    if (u.includes("/api/qbank/entries"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ entries: [{ id: "skill_years", question: "How many years of experience do you have with this skill?", topic: "experience" }] }) });
```

and replace the test `"marking wrong asks for the right answer and sends it"` with:

```jsx
test("marking wrong lets you point it at the right questionnaire entry", async () => {
  mock([ROW]);
  render(<AnswersUsed jobId={1} />);
  fireEvent.click(await screen.findByRole("button", { name: /Wrong: Years of Python/ }));
  const picker = screen.getByLabelText(/Right question for Years of Python/);
  await waitFor(() => expect(global.fetch.mock.calls.some(([u]) => String(u).includes("/api/qbank/entries"))).toBe(true));
  fireEvent.change(picker, { target: { value: "How many years of experience do you have with this skill?" } });
  fireEvent.click(screen.getByRole("button", { name: "Save fix" }));
  await waitFor(() => {
    const post = global.fetch.mock.calls.find(([u]) => String(u).includes("/review"));
    expect(JSON.parse(post[1].body)).toEqual({ verdict: "wrong", entry_id: "skill_years" });
  });
  expect(await screen.findByText("marked wrong")).toBeInTheDocument();
});
```

Append to `frontend/src/__tests__/retrieval_panel.test.jsx`:

```jsx
test("shows how often questionnaire matches were changed, by score band", async () => {
  mock({ ...STATS, by_band: [{ band: "0.6–0.7", kept: 3, edited: 2, edit_rate: 0.4 }] });
  render(<RetrievalPanel />);
  expect(await screen.findByTestId("by-band")).toHaveTextContent("score 0.6–0.7: 40% changed (2 of 5)");
});
```

In `frontend/src/__tests__/tracker_board.test.jsx` change `{ name: "Save to memory" }` to `{ name: "Save answer" }` and the expected body `{ answer: "Because fraud ML." }` to `{ answer: "Because fraud ML.", save_as: "once", entry_id: null }`.

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/__tests__/answers_tab.test.jsx src/__tests__/answers_used.test.jsx src/__tests__/retrieval_panel.test.jsx src/__tests__/tracker_board.test.jsx`
Expected: FAIL (e.g. "Unable to find an element with the text: 1 unanswered").

- [ ] **Step 5: Rewrite `frontend/src/components/AnswersTab.jsx`**

```jsx
import React, { useCallback, useEffect, useState } from "react";
import RetrievalPanel from "./RetrievalPanel.jsx";
import {
  fetchAnswers, saveAnswer, deleteAnswer, fetchAgentSettings, saveAgentSettings, fetchIngredients,
} from "../api.js";

const BTN = { border: "none", cursor: "pointer", fontSize: 12, padding: "5px 12px", borderRadius: "var(--radius-pill)" };
const INPUT = { fontSize: 12, padding: "6px 10px", border: "0.5px solid var(--hairline)", borderRadius: 8, background: "var(--canvas)", color: "var(--ink)", width: "100%", boxSizing: "border-box" };
const CARD = { background: "var(--card)", border: "0.5px solid var(--hairline)", borderRadius: 10, padding: "10px 14px" };
const TOPICS = [
  ["work_auth", "Work authorization"], ["compensation", "Compensation"], ["availability", "Availability"],
  ["location", "Location"], ["experience", "Experience & education"], ["background", "Background"],
  ["demographics", "Demographics (voluntary)"], ["misc", "Other"],
];
const unanswered = (a) => a.needs_input && a.value == null;

function Thresholds() {
  const [s, setS] = useState(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { fetchAgentSettings().then(setS).catch(() => {}); }, []);
  if (!s) return null;
  const save = () => saveAgentSettings({
    answer_confidence_min: Number(s.answer_confidence_min), qbank_confident_min: Number(s.qbank_confident_min),
  }).then(() => { setSaved(true); setTimeout(() => setSaved(false), 1500); });
  const row = (key, id, label, hint) => (
    <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
      <label htmlFor={id} style={{ fontSize: 12, color: "var(--ink)" }}>{label}</label>
      <input id={id} type="number" min="0" max="100" value={s[key]} style={{ ...INPUT, width: 70 }}
             onChange={(e) => setS({ ...s, [key]: e.target.value })} />
      <span style={{ fontSize: 11, color: "var(--ink-faint)" }}>{hint}</span>
    </div>
  );
  return (
    <div style={{ ...CARD, display: "flex", flexDirection: "column", gap: 8, marginBottom: 12 }}>
      {row("qbank_confident_min", "qbank-min", "Minimum match score to fill from the questionnaire without flagging",
           "Below this, the best match is still filled but listed for you to check before submit.")}
      {row("answer_confidence_min", "conf-min", "Minimum confidence to fill a generated answer",
           "Below this (or unknown) a drafted answer is not filled.")}
      <div><button onClick={save} aria-label="Save thresholds" style={{ ...BTN, background: "var(--green)", color: "#fff" }}>{saved ? "Saved" : "Save"}</button></div>
    </div>
  );
}

function Ingredients() {
  const [d, setD] = useState(null);
  useEffect(() => { fetchIngredients().then(setD).catch(() => {}); }, []);
  if (!d || !d.units.length) return null;
  return (
    <details style={{ marginTop: 16 }}>
      <summary style={{ fontSize: 12, color: "var(--ink-soft)", cursor: "pointer" }}>
        Ingredients ({d.units.length}) — read-only, edited in ingredients.json
      </summary>
      <ul style={{ margin: "6px 0 0", paddingLeft: 16, fontSize: 12, color: "var(--ink-soft)" }}>
        {d.units.map((u) => <li key={u.id}>{u.title}{u.org ? ` · ${u.org}` : ""} <em>({u.type})</em></li>)}
      </ul>
    </details>
  );
}

function Entry({ a, onSave, onRemove }) {
  const [draft, setDraft] = useState(a.answer ?? "");
  const input = a.atype === "bool"
    ? <select aria-label={`Answer for ${a.question}`} value={draft} onChange={(e) => setDraft(e.target.value)} style={{ ...INPUT, width: 120 }}>
        <option value="">—</option><option>Yes</option><option>No</option>
      </select>
    : <input aria-label={`Answer for ${a.question}`} value={draft} onChange={(e) => setDraft(e.target.value)} style={INPUT} />;
  return (
    <div data-testid={`entry-${a.id}`} style={{ ...CARD, borderColor: unanswered(a) ? "var(--warm-ink)" : "var(--hairline)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)" }}>{a.question}</div>
        <button aria-label={`Remove ${a.question}`} onClick={() => onRemove(a)}
                style={{ ...BTN, background: "var(--dupe-bg)", color: "var(--dupe-ink)", flexShrink: 0 }}>Remove</button>
      </div>
      {a.profile_ref ? (
        <div style={{ fontSize: 12, color: "var(--ink-soft)", marginTop: 4 }}>
          <span>{a.value ?? "not set"}</span> <em>— from your profile ({a.profile_ref})</em>
        </div>
      ) : a.needs_input ? (
        <div style={{ display: "flex", gap: 6, marginTop: 6, alignItems: "center" }}>
          {input}
          <button aria-label={`Save ${a.question}`} disabled={!draft.trim()} onClick={() => onSave(a, draft)}
                  style={{ ...BTN, background: "var(--green)", color: "#fff" }}>Save</button>
        </div>
      ) : null}
      {a.rule_help && <div style={{ fontSize: 11, color: "var(--ink-faint)", marginTop: 4 }}>{a.rule_help}</div>}
      <details style={{ marginTop: 4 }}>
        <summary style={{ fontSize: 11, color: "var(--ink-soft)", cursor: "pointer" }}>
          {a.asked_in ? `asked in ${a.asked_in} application${a.asked_in === 1 ? "" : "s"}` : "not asked yet"}
          {` · ${a.wordings.length} wording${a.wordings.length === 1 ? "" : "s"}`}
        </summary>
        <ul style={{ margin: "2px 0 0", paddingLeft: 16, fontSize: 11, color: "var(--ink-soft)" }}>
          {a.wordings.map((w) => <li key={w}>{w}</li>)}
        </ul>
      </details>
    </div>
  );
}

export default function AnswersTab() {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [err, setErr] = useState(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ question: "", answer: "" });

  const load = useCallback(() => {
    fetchAnswers(q).then((d) => { setData(d); setErr(null); }).catch((e) => setErr(String(e)));
  }, [q]);
  useEffect(() => { load(); }, [load]);

  const save = (a, answer) => saveAnswer({ entry_id: a.id, answer }).then(load).catch((e) => setErr(String(e)));
  const remove = (a) => {
    if (window.confirm(`Remove "${a.question}" from the questionnaire?`)) deleteAnswer(a.id).then(load).catch((e) => setErr(String(e)));
  };
  const add = () => saveAnswer(draft).then(() => { setDraft({ question: "", answer: "" }); setAdding(false); load(); })
    .catch((e) => setErr(String(e)));

  const shown = data ? data.answers.filter((a) => !onlyOpen || unanswered(a)) : [];
  return (
    <div style={{ marginTop: 14 }}>
      <Thresholds />
      <RetrievalPanel />
      <div style={{ display: "flex", gap: 8, marginBottom: 10, alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ fontSize: 13 }}>Questionnaire</strong>
        {data && <span style={{ fontSize: 12, color: "var(--warm-ink)" }}>{data.unanswered} unanswered</span>}
        <label style={{ fontSize: 12, display: "flex", gap: 4, alignItems: "center" }}>
          <input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} aria-label="Only unanswered" />
          Only unanswered
        </label>
        <button onClick={() => setAdding(!adding)} style={{ ...BTN, background: "var(--green)", color: "#fff", marginLeft: "auto" }}>+ Add question</button>
      </div>
      <input aria-label="Search questions" placeholder="Search questions and answers…" value={q}
             onChange={(e) => setQ(e.target.value)} style={{ ...INPUT, marginBottom: 10 }} />
      {err && <div role="alert" style={{ color: "var(--dupe-ink)", fontSize: 12, marginBottom: 8 }}>{err}</div>}
      {adding && (
        <div style={{ ...CARD, display: "flex", flexDirection: "column", gap: 6, marginBottom: 10 }}>
          <input aria-label="New question" placeholder="Question, as the form words it" value={draft.question}
                 onChange={(e) => setDraft({ ...draft, question: e.target.value })} style={INPUT} />
          <input aria-label="New answer" placeholder="Answer" value={draft.answer}
                 onChange={(e) => setDraft({ ...draft, answer: e.target.value })} style={INPUT} />
          <div><button style={{ ...BTN, background: "var(--green)", color: "#fff" }} onClick={add}>Save</button></div>
        </div>
      )}
      {data === null ? <div style={{ color: "var(--ink-soft)", padding: 16 }}>Loading questionnaire…</div>
        : TOPICS.map(([key, title]) => {
          const items = shown.filter((a) => (a.topic || "misc") === key);
          if (!items.length) return null;
          return (
            <section key={key} style={{ marginBottom: 14 }}>
              <h3 style={{ fontSize: 13, color: "var(--ink-soft)", margin: "8px 0" }}>{title}</h3>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {items.map((a) => <Entry key={a.id} a={a} onSave={save} onRemove={remove} />)}
              </div>
            </section>
          );
        })}
      <Ingredients />
    </div>
  );
}
```

- [ ] **Step 6: Update `QuestionsPanel.jsx`**

Add `import EntryPicker from "./EntryPicker.jsx";` to the imports. Add state `const [mode, setMode] = useState({});` and `const [pick, setPick] = useState({});` after `const [text, setText] = useState({});`. Replace the `reply` function with:

```jsx
  const reply = (q) => {
    const answer = (text[q.id] ?? q.answer ?? "").trim();
    const m = mode[q.id] || "once";
    if (!answer || (m === "wording" && !pick[q.id])) return;
    replyQuestion(jobId, q.id, answer, m, m === "wording" ? pick[q.id] : null)
      .then(() => { setErr(null); load(); if (onChanged) onChanged(); })
      .catch((e) => setErr(String(e)));
  };
```

Inside each question card, directly after `<div style={{ fontSize: 12, fontWeight: 600, color: "var(--warm-ink)" }}>{q.label}</div>`, add:

```jsx
            {q.source === "qbank_likely" && (
              <div style={{ fontSize: 11, color: "var(--ink-soft)", margin: "2px 0 6px" }}>
                Filled with a best guess from your questionnaire (“{q.retrieved_qkey}”, score {q.retrieval_score}) — check it.
              </div>
            )}
            {q.asked_in > 1 && (
              <div style={{ fontSize: 11, color: "var(--warm-ink)" }}>Asked in {q.asked_in} applications — worth saving to the questionnaire.</div>
            )}
```

Replace the `<button onClick={() => reply(q)} …>Save to memory</button>` element with:

```jsx
            <div role="radiogroup" aria-label={`Save ${q.label} as`} style={{ display: "flex", gap: 10, fontSize: 11, margin: "6px 0" }}>
              {[["once", "Just this application"], ["new", "New questionnaire entry"], ["wording", "Another wording of…"]].map(([v, t]) => (
                <label key={v}><input type="radio" name={`mode-${q.id}`} checked={(mode[q.id] || "once") === v}
                                      onChange={() => setMode({ ...mode, [q.id]: v })} /> {t}</label>
              ))}
            </div>
            {mode[q.id] === "wording" && (
              <EntryPicker id={`pick-${q.id}`} label={`Questionnaire entry for ${q.label}`}
                           onChange={(eid) => setPick({ ...pick, [q.id]: eid })} />
            )}
            <button onClick={() => reply(q)}
                    style={{ marginTop: 6, border: "none", cursor: "pointer", fontSize: 12, padding: "5px 12px",
                             borderRadius: "var(--radius-pill)", background: "var(--green)", color: "#fff" }}>
              Save answer
            </button>
```

- [ ] **Step 7: Update `AnswersUsed.jsx`**

Add `import EntryPicker from "./EntryPicker.jsx";`. Change the `fixing` state comment to `// {id, entry}`. Replace the `fixing && fixing.id === r.id ? ( … )` branch's `<div>` (the one holding the `Correct answer for` input and `Save fix` button) with:

```jsx
              <div style={{ display: "flex", gap: 6, marginTop: 4, alignItems: "center" }}>
                <EntryPicker id={`fix-${r.id}`} label={`Right question for ${r.label}`}
                             onChange={(entry) => setFixing({ id: r.id, entry })} />
                <button style={{ ...BTN, background: "var(--green)", color: "#fff", whiteSpace: "nowrap" }}
                        onClick={() => send(r.id, "wrong", fixing.entry)}>Save fix</button>
              </div>
```

and change the Wrong button's `onClick={() => setFixing({ id: r.id, answer: "" })}` to `onClick={() => setFixing({ id: r.id, entry: null })}`.

- [ ] **Step 8: Update `RetrievalPanel.jsx`**

Replace the `TIER` constant with:

```jsx
const TIER = { purpose: "same purpose", label_exact: "exact question", fts_fuzzy: "similar wording", semantic: "similar meaning",
               exact: "same wording", shortlist: "similar meaning", llm: "LLM picked from shortlist", none: "no match" };
```

Change the `stat-unused` hint to `"matched an entry but didn't fill (unanswered entry, no option fit, or below the floor)"`. After the `top_wrong_entries` block, add:

```jsx
      {s.by_band && s.by_band.length > 0 && (
        <div style={{ ...CARD, marginBottom: 8 }} data-testid="by-band">
          <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 4 }}>Questionnaire matches you changed, by match score</div>
          {s.by_band.map((b) => (
            <div key={b.band} style={{ fontSize: 12, color: "var(--ink-soft)" }}>
              score {b.band}: {pct(b.edit_rate)} changed ({b.edited} of {b.kept + b.edited})
            </div>
          ))}
          <div style={{ fontSize: 11, color: "var(--ink-faint)" }}>Set “minimum match score” above the bands you often change.</div>
        </div>
      )}
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd frontend && npx vitest run`
Expected: all test files pass.

- [ ] **Step 10: Check it in the browser**

Start the dashboard (the project's `.claude/launch.json` entry via `preview_start`), open the Answers tab, confirm: topic sections render, the unanswered counter drops after saving a Yes/No answer, and a profile-backed entry shows its profile value. Take a screenshot for the commit/PR.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/api.js frontend/src/components/EntryPicker.jsx frontend/src/components/AnswersTab.jsx frontend/src/components/QuestionsPanel.jsx frontend/src/components/AnswersUsed.jsx frontend/src/components/RetrievalPanel.jsx frontend/src/__tests__/answers_tab.test.jsx frontend/src/__tests__/answers_used.test.jsx frontend/src/__tests__/retrieval_panel.test.jsx frontend/src/__tests__/tracker_board.test.jsx
git commit -m "feat(dashboard): questionnaire tab, save-as choices, re-point wrong matches, edit rate by score band"
```

---

### Task 10: Knowledge graph + docs + memory

**Files:**
- Modify: `docs/career-agent/ats-graph.json` (via `scripts/ats_graph.py` helpers)
- Modify: `src/career_agent/CLAUDE.md` (fill ladder + memory table)
- Modify: `~/.claude/projects/-Users-rakshitsingh-Desktop-My-project-Job-Dashboard/memory/career-agent-user-answers.md` and `MEMORY.md`

- [ ] **Step 1: Mark superseded approaches in the graph**

```bash
PYTHONPATH=src python3 - <<'EOF'
import sys; sys.path.insert(0, "scripts")
import ats_graph as g
g.add_node({"id": "code:qbank", "type": "code", "label": "Question bank (memory/qbank*.py)", "status": "current",
            "note": "canonical questions answered once on the dashboard; exact wording -> embedding shortlist -> LLM pick-or-none; bands confident/likely/none; spec docs/superpowers/specs/2026-09-26-question-bank-design.md"})
for old, label in [("code:learned_answers", "learned_answers FTS recall keyed by label/purpose"),
                   ("code:semantic_behavior", "Chroma behavioral_qa vault with 3-approval autonomy")]:
    g.add_node({"id": old, "type": "code", "label": label, "status": "superseded"})
    g.add_edge({"from": "code:qbank", "to": old, "rel": "SUPERSEDES"})
print(g.query("qbank"))
EOF
python3 scripts/ats_graph.py demo
```

Expected: the query prints the `code:qbank` node with two SUPERSEDES edges; `demo` prints `ok: 89 nodes 56 edges`.

- [ ] **Step 2: Update `src/career_agent/CLAUDE.md`**

Replace the `## fill_node answer ladder` list items 1–2 with:

```markdown
1. **Question bank** — `memory/qbank*.py` (jobs.db `qbank_entry`/`qbank_wording`) — exact wording → embedding shortlist → LLM picks an entry id or NONE (never writes a value). Confident = fill; likely = fill + listed for review before submit; none = falls through. Answers are typed once on the dashboard's Answers tab. Maintenance: `PYTHONPATH=src python3 scripts/qbank.py seed|migrate|calibrate`.
```

and renumber the remaining items 2–4. In the `## Tri-Partite Memory` table, append ` — **superseded for the fill loop by the question bank; still used by MCP tools**` to the `SEMANTIC_MATCH` and `RECORD_FEEDBACK` rows. In `## Data paths`, change `SQLite (jobs, learned_answers, profile)` to `SQLite (jobs, qbank_entry/qbank_wording, profile)`.

- [ ] **Step 3: Update Claude memory**

In `career-agent-user-answers.md`, add at the top of the body: `**As of 2026-09-27 these values live in the question bank (jobs.db qbank_entry, edited on the dashboard Answers tab). This note is history; the bank is the source of truth.** See [[career-agent-question-bank]].` Create `career-agent-question-bank.md` (type `project`) recording: what the bank is, the faithfulness rule, the three bands, the calibrated FLOOR/MARGIN/HIGH values from Task 4, and the deferred items (Telegram save-as, retiring `standard_answers`, repointing `memory_router`). Add its one-line pointer to `MEMORY.md`.

- [ ] **Step 4: Final full check**

Run: `PYTHONPATH=src python3 -m pytest tests -q` and `cd frontend && npx vitest run`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add docs/career-agent/ats-graph.json src/career_agent/CLAUDE.md
git commit -m "docs(qbank): mark learned_answers + semantic vault superseded; update agent run map"
```

---

## After the build (user steps, not code)

1. Open the dashboard Answers tab → tick **Only unanswered** → answer the questionnaire (the entries backed by your profile are already filled).
2. Run one real dry run with a `--job-id` so company/location rules have data: `PYTHONPATH=src python3 -m career_agent.apply --job-id <N>`.
3. Review the job's flagged questions and "Answers filled" list; mark right/wrong. After a few dozen applications, read **edit rate by score band** and adjust "minimum match score".
