# Story Answers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Five guided long-form "story" answers in the question bank feed the essay drafter, so founder messages / why-us answers use the candidate's own words plus the job page.

**Architecture:** Story entries are ordinary bank rows (`topic: "story"`) excluded from field matching; `qbank.story_text(conn)` renders them; `JudgmentContext.story_text` → `judge` → `draft_screening_answer(story_text=)` whose prompt gains an own-words block and treats the job page as an allowed company source.

**Spec:** `docs/superpowers/specs/2026-09-27-story-answers-design.md`

## Global Constraints
- Story answers are never filled into form fields verbatim.
- Company specifics only from the job page (COMPANY & ROLE) or VERIFIED COMPANY FACTS; never invented.
- `draft_screening_answer(..., story_text="")` default keeps other callers unchanged.
- No `Co-Authored-By`. Files < 500 lines. `PYTHONPATH=src python3 -m pytest …`; `cd frontend && npx vitest run`.

---

### Task S1: Backend — story entries, story_text, drafting prompt

**Files:** `data/qbank_seed.json`, `src/career_agent/memory/qbank.py`, `src/career_agent/orchestrator/judgment.py`, `src/job_dashboard/apply/screening.py`, `src/career_agent/apply.py`; tests `tests/career_agent/test_qbank.py`, `tests/career_agent/test_judgment.py`, `tests/test_screening*.py` (whichever file already tests `screening._build_prompt`/`draft_screening_answer`; create `tests/test_screening_story.py` if none).

- [ ] **Step 1: Failing tests**

Append to `tests/career_agent/test_qbank.py`:

```python
def test_story_entries_never_match_and_render(fake_embed, tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"entries": [
        {"id": "story_why_startups", "topic": "story", "atype": "text",
         "question": "Why do you want to work at an early-stage startup?"},
        {"id": "story_problems", "topic": "story", "atype": "text",
         "question": "What kinds of problems excite you?"},
        {"id": "notice_period", "topic": "availability", "atype": "number",
         "question": "What is your notice period?"}]}))
    c = _conn()
    qbank.load_seed(c, fake_embed, seed)
    assert qbank.exact(c, "Why do you want to work at an early-stage startup?") is None
    assert {e for _, e, _ in qbank.wordings(c)} == {"notice_period"}
    assert qbank.story_text(c) == ""
    qbank.set_answer(c, "story_why_startups", "I like owning outcomes.")
    assert qbank.story_text(c) == ("Q: Why do you want to work at an early-stage startup?\n"
                                   "A: I like owning outcomes.")


def test_real_seed_has_five_story_prompts():
    raw = json.loads(qbank.SEED_PATH.read_text())["entries"]
    assert sorted(e["id"] for e in raw if e["topic"] == "story") == [
        "story_how_you_work", "story_looking_for", "story_problems",
        "story_proudest_work", "story_why_startups"]
```

Screening test (in the existing screening test file, or new `tests/test_screening_story.py`):

```python
from job_dashboard.apply.screening import _build_prompt, draft_screening_answer

JOB = {"title": "ML Engineer", "company": "HUD", "description": "HUD builds RL environments for agents. " * 80}


def test_prompt_has_own_words_and_company_page():
    p = _build_prompt(JOB, "Why HUD?", "Data scientist", None, JOB["description"], "Q: Why startups?\nA: Ownership.")
    assert "IN THE CANDIDATE'S OWN WORDS" in p and "A: Ownership." in p
    assert "COMPANY & ROLE (from the job page)" in p and "RESUME EXCERPT" not in p
    assert p.count("HUD builds RL environments") > 10          # 2000-char page window, not 800


def test_prompt_omits_own_words_when_empty():
    assert "OWN WORDS" not in _build_prompt(JOB, "Why HUD?", "x", None, "", "")


def test_draft_passes_story_to_prompt():
    seen = []
    res = draft_screening_answer(JOB, "Why HUD?", "Data scientist", None, JOB["description"],
                                 llm=lambda p: seen.append(p) or '{"answer": "Because.", "confidence": 80, "basis": "b"}',
                                 story_text="Q: Why startups?\nA: Ownership.")
    assert "A: Ownership." in seen[0] and res["answer"] == "Because."
```

Append to `tests/career_agent/test_judgment.py` (reuse that file's existing field helper/fake llm style; if none fits, use this):

```python
def test_judge_forwards_story_text(monkeypatch):
    from career_agent.browser.form_model import Field
    from career_agent.orchestrator import judgment
    seen = {}

    def fake_draft(job, q, profile_text, research, resume_text, llm=None, story_text=""):
        seen["story"] = story_text
        return {"answer": "x", "confidence": 90, "basis": "", "prompt": "", "flags": [],
                "unsupported_company_claims": []}
    monkeypatch.setattr(judgment, "draft_screening_answer", fake_draft)
    ctx = judgment.JudgmentContext(job={"title": "t", "company": "c", "description": ""},
                                   story_text="Q: a\nA: b")
    f = Field("#m", "textarea", "Why do you want to join us?", True, [], None, None)
    judgment.judge([f], ctx, llm=lambda p: "")
    assert seen["story"] == "Q: a\nA: b"
```

- [ ] **Step 2: Run, expect FAIL** (`story_text` missing everywhere).

- [ ] **Step 3: Seed** — append to `entries` in `data/qbank_seed.json` (before `]`), no answers:

```json
    {"id": "story_looking_for", "topic": "story", "atype": "text", "question": "What are you looking for in your next role?"},
    {"id": "story_why_startups", "topic": "story", "atype": "text", "question": "Why do you want to work at an early-stage startup?"},
    {"id": "story_proudest_work", "topic": "story", "atype": "text", "question": "What work are you proudest of, and why?"},
    {"id": "story_how_you_work", "topic": "story", "atype": "text", "question": "How do you like to work (team, pace, ownership)?"},
    {"id": "story_problems", "topic": "story", "atype": "text", "question": "What kinds of problems excite you?"}
```

Keep `test_real_seed_file_is_valid` passing (unique wordings).

- [ ] **Step 4: `qbank.py`** — in `exact()` and `wordings()` change `e.status='active'` to `e.status='active' AND e.topic IS NOT 'story'` (story answers must never fill a form field). Add:

```python
def story_text(conn) -> str:
    """Answered story entries as Q/A blocks — context for the essay drafter only."""
    rows = conn.execute("SELECT question, answer FROM qbank_entry WHERE topic='story' "
                        "AND status='active' AND TRIM(COALESCE(answer, '')) != '' ORDER BY id").fetchall()
    return "\n\n".join(f"Q: {q}\nA: {a}" for q, a in rows)
```

- [ ] **Step 5: `screening.py`** — `_MAX_RESUME_CHARS = 800` → `_MAX_PAGE_CHARS = 2000`; add `_MAX_STORY_CHARS = 2500`. `_build_prompt(job, question, profile_text, research, resume_text, story_text="")`:
  - intro sentence: "Answer truthfully in 4-6 sentences."
  - rule 1: ground candidate claims in CANDIDATE PROFILE / OWN WORDS.
  - rule 2: "Mention a company-specific detail ONLY if it appears in COMPANY & ROLE or VERIFIED COMPANY FACTS. Never invent a company fact."
  - new rule 4: "Connect what the candidate says they want and enjoy to what this company does. Warm, specific, first person; no generic filler."
  - blocks: `CANDIDATE PROFILE` (unchanged), then only if `story_text.strip()`: `IN THE CANDIDATE'S OWN WORDS:\n{story_text[:_MAX_STORY_CHARS]}\n\n`, then `COMPANY & ROLE (from the job page):\n{(resume_text or '')[:_MAX_PAGE_CHARS]}` replacing the RESUME EXCERPT block, then VERIFIED COMPANY FACTS as before.
  - `draft_screening_answer(job, question, profile_text, research, resume_text="", llm=None, story_text="")`: pass `story_text` to `_build_prompt`; grounding check uses `(profile_text or "") + "\n" + (story_text or "")` as its profile argument.

- [ ] **Step 6: `judgment.py`** — `JudgmentContext` add `story_text: str = ""   # candidate's own long-form answers (qbank topic=story)`; in `judge()` the `draft_screening_answer(...)` call adds `story_text=ctx.story_text`.

- [ ] **Step 7: `apply.py`** — in `JudgmentContext(...)` (≈L172) add `story_text=_story_text(conn),` with, near the top of that `try`, `from .memory.qbank import story_text as _story_text` (before `ctx = …`). If `qbank_entry` may not exist yet, `qbank.ensure(conn)` first (it is idempotent).

- [ ] **Step 8: GREEN** — focused tests, then `PYTHONPATH=src python3 -m pytest tests/career_agent tests/test_qa_api.py tests/test_screening*.py -q`. Any older screening test asserting "RESUME EXCERPT" or 800 chars: update to the new labels/limits and list it in the report.

- [ ] **Step 9: Commit** — `git commit -m "feat(essays): story answers in the question bank feed founder-message/why-us drafting"`

---

### Task S2: Dashboard — "Your story" section

**Files:** `frontend/src/components/AnswersTab.jsx`, `frontend/src/__tests__/answers_tab.test.jsx`

- [ ] **Step 1: Failing test** — in `answers_tab.test.jsx` add to `DATA.answers`:

```jsx
  { id: "story_why_startups", question: "Why do you want to work at an early-stage startup?", topic: "story",
    atype: "text", answer: null, profile_ref: null, rule: null, rule_help: null, value: null,
    needs_input: true, wordings: [], asked_in: 0 },
```

(and bump `unanswered` to 2), then add:

```jsx
test("story section comes first and uses a multi-line box", async () => {
  mock();
  render(<AnswersTab />);
  const box = await screen.findByLabelText("Answer for Why do you want to work at an early-stage startup?");
  expect(box.tagName).toBe("TEXTAREA");
  const headings = screen.getAllByRole("heading").map((h) => h.textContent);
  expect(headings[0]).toBe("Your story (used to write essays)");
});
```

Fix any existing assertion broken by the new row (e.g. "1 unanswered" → "2 unanswered").

- [ ] **Step 2: FAIL**, then implement: prepend `["story", "Your story (used to write essays)"]` to `TOPICS`; in `Entry`, when `a.topic === "story"` render `<textarea aria-label={`Answer for ${a.question}`} rows={5} …>` instead of the `<input>` (same value/onChange/style).
- [ ] **Step 3: GREEN** — `cd frontend && npx vitest run` all pass.
- [ ] **Step 4: Commit** — `git commit -m "feat(dashboard): Your story section for essay answers"`
