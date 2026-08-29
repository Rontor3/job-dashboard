# Career Agent Phase E — Judgment Tier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer the form fields the rule-based filler escalates — free-text fit questions and option/enum questions — grounded in profile + JD, as drafts behind the dry-run gate.

**Architecture:** A new pure-ish `orchestrator/judgment.py` exposes `judge(needs_human, ctx, llm, cap, orchestrator)` that runs AFTER `map_screen` (which stays pure). It reuses `job_dashboard.apply.screening.draft_screening_answer` (local qwen via `make_default_llm`) for free-text and a `map_option` LLM helper for enums; sensitive fields are never answered; a per-app call cap bounds cost; a tier-3 `orchestrator` callback handles the hardest. Wires into `step_engine.walk` (optional `judge_fn`) and `apply.py` (`--job-id` loads the JD).

**Tech Stack:** Python 3.11, pytest. Reuses `job_dashboard.apply.screening`, `job_dashboard.letter.draft.make_default_llm`. Tests: `PYTHONPATH=src python3 -m pytest tests/career_agent` (flat dir, NO `__init__.py`). Fake `llm`/`post` in unit tests — no live Ollama.

## Global Constraints

- **Grounded & truthful.** Answers derive strictly from CandidateProfile / JD / research; `draft_screening_answer`'s prompt + `check_grounding` guard enforce this. Never fabricate.
- **Sensitive fields never auto-answered.** gender / ethnicity / race / veteran / disability / orientation / pronouns, and attestations — always escalate.
- **Never fill a non-option.** `map_option` returns one of the field's options or `None` (Phase 3B boundary).
- **Bounded cost.** `judge` makes at most `cap` model calls per application (default 6).
- **Draft, not final.** Judged decisions use `source in {"judgment","orchestrator"}` (the review signal); dry-run never submits.
- **LLM-free tests.** Every unit test injects a fake `llm`.
- Branch `career-agent-phase-e`. Commit after each task.

## File Structure

- `src/career_agent/orchestrator/judgment.py` — NEW. `JudgmentContext`, `profile_to_text`, `_is_sensitive`, `map_option`, `judge`.
- `src/career_agent/orchestrator/step_engine.py` — MODIFY `walk` to accept optional `judge_fn`.
- `src/career_agent/apply.py` — MODIFY `main`: `--job-id` loads JD, builds ctx + llm, passes `judge_fn`.
- `src/job_dashboard/db.py` — MODIFY: add `get_job(conn, job_id)` returning `{title, company, description}`.
- Tests: `tests/career_agent/test_judgment.py`, extend `test_step_engine.py`.

---

### Task 1: Judgment helpers — context, profile text, sensitivity, enum mapping

**Files:**
- Create: `src/career_agent/orchestrator/judgment.py`
- Test: `tests/career_agent/test_judgment.py`

**Interfaces:**
- Produces: `JudgmentContext(job: dict, profile_text: str, research=None, resume_text="")`; `profile_to_text(profile) -> str`; `_is_sensitive(field) -> bool`; `map_option(label, options, profile_text, llm) -> str | None`.

- [ ] **Step 1: Write the failing test** — `tests/career_agent/test_judgment.py`

```python
from career_agent.browser.form_model import Field
from career_agent.memory.candidate_profile import CandidateProfile, Experience, Education
from career_agent.orchestrator.judgment import (
    JudgmentContext, profile_to_text, _is_sensitive, map_option,
)


def _f(ref, label, purpose=None, kind="text", options=None, required=False):
    return Field(ref, kind, label, required, options or [], None, purpose)


def test_profile_to_text_includes_experience_and_skills():
    p = CandidateProfile(
        contact={"full_name": "Rakshit Singh"},
        experiences=[Experience("Tata AIG", "Data Scientist", "2023", "Present", ["Built fraud models"])],
        education=[Education("IIT BHU", "B.Tech", "Ceramics")],
        skills=["Python", "SQL"])
    t = profile_to_text(p)
    assert "Rakshit Singh" in t and "Tata AIG" in t and "Data Scientist" in t
    assert "Built fraud models" in t and "Python" in t and "B.Tech" in t


def test_is_sensitive_flags_demographics_and_attestation():
    assert _is_sensitive(_f("#g", "Gender"))
    assert _is_sensitive(_f("#e", "Are you Hispanic/Latino?"))
    assert _is_sensitive(_f("#v", "Have you served in the armed forces?", purpose="veteran"))
    assert _is_sensitive(_f("#d", "Disability status"))
    assert _is_sensitive(_f("#a", "I certify this is true", purpose="attestation"))
    assert not _is_sensitive(_f("#q", "Why do you want this role?", kind="textarea"))


def test_map_option_picks_a_real_option_or_none():
    # fake llm echoes a fixed choice
    opts = ["High school", "Bachelor's degree", "Master's degree"]
    llm_ok = lambda prompt: "Bachelor's degree"
    assert map_option("Highest level of education", opts, "B.Tech from IIT", llm_ok) == "Bachelor's degree"
    # llm returns something not in options -> None (never fill a non-option)
    llm_bad = lambda prompt: "PhD"
    assert map_option("Highest level of education", opts, "B.Tech", llm_bad) is None
    # llm says NONE -> None
    llm_none = lambda prompt: "NONE"
    assert map_option("Highest level of education", opts, "B.Tech", llm_none) is None
```

- [ ] **Step 2: Run to verify it fails** — `PYTHONPATH=src python3 -m pytest tests/career_agent/test_judgment.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement `judgment.py`**

```python
"""Phase E judgment tier: answer the fields map_screen escalated, grounded in
profile + JD, as drafts behind the dry-run gate. LLM-free-testable (inject llm)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field as _field


@dataclass
class JudgmentContext:
    job: dict                      # {title, company, description}
    profile_text: str = ""
    research: object = None        # ResearchBundle or None (draft handles None)
    resume_text: str = ""


_SENSITIVE_RE = re.compile(
    r"\bgender\b|\bethnic|\brace\b|\bhispanic\b|\blatino\b|\bveteran\b|"
    r"\barmed forces\b|\bdisab|\bsexual orientation\b|\bpronoun", re.I)
_SENSITIVE_PURPOSES = {"veteran", "attestation"}


def _is_sensitive(field) -> bool:
    if field.purpose in _SENSITIVE_PURPOSES:
        return True
    return bool(_SENSITIVE_RE.search(field.label or ""))


def profile_to_text(profile) -> str:
    parts = []
    c = profile.contact or {}
    if c.get("full_name"):
        parts.append(f"Name: {c['full_name']}")
    for e in profile.experiences:
        head = f"{e.title} at {e.company} ({e.start}-{e.end})".strip()
        parts.append("Experience: " + head)
        for b in e.bullets:
            parts.append(f"  - {b}")
    for ed in profile.education:
        parts.append(f"Education: {ed.degree} {ed.field} at {ed.school}".strip())
    if profile.skills:
        parts.append("Skills: " + ", ".join(profile.skills))
    return "\n".join(parts)


def map_option(label, options, profile_text, llm) -> str | None:
    """Ask the llm to pick exactly one of `options` for the field, or NONE.
    Validates the reply against `options` (never returns a non-option)."""
    opts = [o for o in (options or []) if o and o.strip().lower() not in ("select an option", "select...")]
    if not opts:
        return None
    prompt = (
        "Pick the ONE option that best answers the application question for this "
        "candidate. Reply with the option text EXACTLY as written, or the word "
        "NONE if none fit.\n\n"
        f"QUESTION: {label}\nOPTIONS:\n" + "\n".join(f"- {o}" for o in opts) +
        f"\n\nCANDIDATE:\n{(profile_text or '')[:1500]}\n\nAnswer with one option or NONE:")
    try:
        reply = (llm(prompt) or "").strip()
    except Exception:
        return None
    low = reply.lower()
    for o in opts:
        if o.strip().lower() == low:
            return o
    return None
```

- [ ] **Step 4: Run** — `PYTHONPATH=src python3 -m pytest tests/career_agent/test_judgment.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/orchestrator/judgment.py tests/career_agent/test_judgment.py
git commit -m "feat(career-agent): judgment helpers — context, profile text, sensitivity, enum map (Phase E task 1)"
```

---

### Task 2: `judge()` — the judgment pass

**Files:**
- Modify: `src/career_agent/orchestrator/judgment.py`
- Test: extend `tests/career_agent/test_judgment.py`

**Interfaces:**
- Consumes: `JudgmentContext`, `_is_sensitive`, `map_option` (Task 1); `draft_screening_answer` (`job_dashboard.apply.screening`); `FillDecision`, `_action_for_kind` (`orchestrator.mapper`).
- Produces: `judge(needs_human, ctx, llm, cap=6, orchestrator=None) -> (answered: list[FillDecision], still_need: list[Field], flagged: set[str])`.

- [ ] **Step 1: Write the failing test** — extend `test_judgment.py`

```python
from career_agent.orchestrator.judgment import judge


def test_judge_answers_freetext_flags_and_escalates_sensitive():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme", "description": "..."},
                          profile_text="Rakshit, Data Scientist at Tata AIG")
    freetext = _f("#q", "Why do you want this role?", kind="textarea", required=True)
    gender = _f("#g", "Gender", kind="text")
    llm = lambda prompt: "I'm excited about Acme because of my ML work at Tata AIG."
    answered, still_need, flagged = judge([freetext, gender], ctx, llm, cap=6)
    d = {x.ref: x for x in answered}
    assert d["#q"].source == "judgment" and "Acme" in d["#q"].value
    assert "#g" in {f.ref for f in still_need}          # sensitive -> escalate
    assert "#q" not in {f.ref for f in still_need}


def test_judge_maps_enum_or_escalates():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="B.Tech IIT")
    edu = _f("#edu", "Highest level of education", kind="select",
             options=["Bachelor's degree", "Master's degree"], required=True)
    llm = lambda prompt: "Bachelor's degree"
    answered, still_need, flagged = judge([edu], ctx, llm)
    assert {x.ref: x for x in answered}["#edu"].value == "Bachelor's degree"


def test_judge_respects_cap():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    q1 = _f("#q1", "Why us?", kind="textarea", required=True)
    q2 = _f("#q2", "Why now?", kind="textarea", required=True)
    llm = lambda prompt: "grounded answer"
    answered, still_need, flagged = judge([q1, q2], ctx, llm, cap=1)
    assert len(answered) == 1 and len(still_need) == 1   # cap hit -> one escalates


def test_judge_never_raises_on_llm_failure():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    q = _f("#q", "Why?", kind="textarea", required=True)
    def boom(prompt): raise RuntimeError("ollama down")
    answered, still_need, flagged = judge([q], ctx, boom, cap=6)
    # draft_screening_answer catches llm errors and returns a general_fallback
    # answer -> filled but flagged; never raises.
    assert "#q" in ({x.ref for x in answered} | {f.ref for f in still_need})
```

- [ ] **Step 2: Run to verify failure** → FAIL (`judge` undefined).

- [ ] **Step 3: Implement `judge`** — append to `judgment.py`

```python
from ..orchestrator.mapper import FillDecision, _action_for_kind
from job_dashboard.apply.screening import draft_screening_answer

_SELECT_KINDS = {"select", "radio_group"}
_FREETEXT_KINDS = {"text", "textarea"}


def judge(needs_human, ctx, llm, cap=6, orchestrator=None):
    answered, still_need, flagged = [], [], set()
    calls = 0
    hard = []                                  # (field) routed to tier-3 orchestrator
    for f in needs_human:
        if _is_sensitive(f):
            still_need.append(f); continue
        if calls >= cap:
            still_need.append(f); continue
        if f.kind in _SELECT_KINDS:
            calls += 1
            opt = map_option(f.label, f.options, ctx.profile_text, llm)
            if opt is None:
                still_need.append(f)
            else:
                answered.append(FillDecision(f.ref, f.kind, f.label, opt,
                                             _action_for_kind(f.kind), "judgment"))
            continue
        if f.kind in _FREETEXT_KINDS and f.purpose is None:
            calls += 1
            res = draft_screening_answer(ctx.job, f.label, ctx.profile_text,
                                         ctx.research, ctx.resume_text, llm=llm)
            weak = res.get("flags") or res.get("unsupported_company_claims")
            if weak and orchestrator is not None:
                hard.append(f); continue       # send the weak ones to tier-3
            answered.append(FillDecision(f.ref, f.kind, f.label, res["answer"], "fill", "judgment"))
            if weak:
                flagged.add(f.ref)
            continue
        still_need.append(f)                    # unhandled kind -> escalate
    # tier-3: the orchestrator (Claude Code) answers the hard ones
    if hard and orchestrator is not None:
        try:
            replies = orchestrator([{"ref": f.ref, "label": f.label,
                                     "job": ctx.job, "profile_text": ctx.profile_text}
                                    for f in hard]) or {}
        except Exception:
            replies = {}
        for f in hard:
            ans = replies.get(f.ref)
            if ans:
                answered.append(FillDecision(f.ref, f.kind, f.label, ans, "fill", "orchestrator"))
            else:
                still_need.append(f)
    return answered, still_need, flagged
```

- [ ] **Step 4: Run** — `test_judgment.py` → PASS. Then full career_agent suite green.

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/orchestrator/judgment.py tests/career_agent/test_judgment.py
git commit -m "feat(career-agent): judge() judgment pass — free-text + enum + sensitive + cap + tier-3 (Phase E task 2)"
```

---

### Task 3: Wire `judge` into the walk

**Files:**
- Modify: `src/career_agent/orchestrator/step_engine.py`
- Test: extend `tests/career_agent/test_step_engine.py`

**Interfaces:**
- Consumes: `judge`-shaped callable `judge_fn(needs) -> (answered, still_need, flagged)`.
- Produces: `walk(..., judge_fn=None)`; when set, judged decisions are filled and only `still_need` goes to `human.collect`.

- [ ] **Step 1: Write the failing test** — extend `test_step_engine.py`

```python
def test_walk_uses_judge_fn_before_human_collect():
    s1 = [_f("#q", "Why us?", None, required=True, kind="textarea"),
          _f("#c", "Submit application", None, kind="button")]
    deps = Deps([s1])
    prof = CandidateProfile(contact={})
    seen = {}
    class H(Human):
        def collect(self, fields): seen["refs"] = [f.ref for f in fields]; return {}
    def judge_fn(needs):
        from career_agent.orchestrator.mapper import FillDecision
        return ([FillDecision("#q", "textarea", "Why us?", "Because ML.", "fill", "judgment")], [], set())
    walk(object(), prof, H(), deps, do_submit=True, autonomous=True, judge_fn=judge_fn)
    filled = [d for batch in deps.filled for d in batch]
    assert any(d.ref == "#q" and d.source == "judgment" for d in filled)
    assert seen.get("refs") == []          # nothing left for the human
```

- [ ] **Step 2: Run to verify failure** → FAIL (`walk` has no `judge_fn`).

- [ ] **Step 3: Modify `walk`** — add the param and use it. In `src/career_agent/orchestrator/step_engine.py`, change the signature:

```python
def walk(page, profile, human, deps, max_steps=15, do_submit=False,
         autonomous=False, on_link=None, resume_pdf=None, judge_fn=None) -> dict:
```

Replace the `map_screen` + escalate block:

```python
        decisions, needs = map_screen(form, profile, resume_pdf)
        if needs and judge_fn is not None:
            answered, needs, _flagged = judge_fn(needs)
            decisions += answered
        if needs:
            decisions += apply_answers(needs, human.collect(needs))
        deps.fill(page, decisions)
```

- [ ] **Step 4: Run** — the new test + all `test_step_engine.py` → PASS; full career_agent suite green.

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/orchestrator/step_engine.py tests/career_agent/test_step_engine.py
git commit -m "feat(career-agent): walk threads an optional judge_fn before human escalation (Phase E task 3)"
```

---

### Task 4: Load the JD by job-id (db helper)

**Files:**
- Modify: `src/job_dashboard/db.py`
- Test: `tests/career_agent/test_get_job.py` (new)

**Interfaces:**
- Produces: `get_job(conn, job_id) -> dict | None` = `{"title", "company", "description"}`.

- [ ] **Step 1: Write the failing test** — `tests/career_agent/test_get_job.py`

```python
import sqlite3
from job_dashboard.db import get_job


def test_get_job_returns_title_company_description():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT, company TEXT, description TEXT)")
    conn.execute("INSERT INTO jobs (id, title, company, description) VALUES (1, 'Data Scientist', 'Acme', 'Build ML.')")
    conn.commit()
    assert get_job(conn, 1) == {"title": "Data Scientist", "company": "Acme", "description": "Build ML."}
    assert get_job(conn, 999) is None
```

- [ ] **Step 2: Run to verify failure** → FAIL (`get_job` undefined).

- [ ] **Step 3: Implement `get_job`** — add to `src/job_dashboard/db.py`

```python
def get_job(conn, job_id):
    """The (title, company, description) for a job id, or None."""
    row = conn.execute(
        "SELECT title, company, description FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    if row is None:
        return None
    return {"title": row[0], "company": row[1], "description": row[2]}
```

- [ ] **Step 4: Run** — `test_get_job.py` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/db.py tests/career_agent/test_get_job.py
git commit -m "feat(db): get_job(conn, id) -> title/company/description for the career agent (Phase E task 4)"
```

---

### Task 5: Wire the judgment tier into `apply.py`

**Files:**
- Modify: `src/career_agent/apply.py`
- Test: import-smoke (`python3 -c "import career_agent.apply"`) + manual live note.

**Interfaces:**
- Consumes: `get_job` (Task 4), `JudgmentContext`, `profile_to_text`, `judge` (Tasks 1-2), `make_default_llm`, `walk(..., judge_fn=)` (Task 3).

- [ ] **Step 1: Add `--job-id` and build the judgment tier** — in `main()` of `src/career_agent/apply.py`, after `profile = load_candidate_profile(...)` and the résumé-pdf block, add:

```python
    ap.add_argument("--job-id", type=int, default=None,
                    help="jobs-table id whose JD grounds free-text answers")
    # (place the add_argument with the others, before parse_args)
    ...
    judge_fn = None
    try:
        from .orchestrator.judgment import JudgmentContext, profile_to_text, judge
        from job_dashboard.db import get_job
        from job_dashboard.letter.draft import make_default_llm
        job = get_job(conn, args.job_id) if args.job_id else None
        if job is None:
            job = {"title": "", "company": "", "description": ""}
        llm = make_default_llm()
        ctx = JudgmentContext(job=job, profile_text=profile_to_text(profile),
                              resume_text=job.get("description", ""))
        judge_fn = lambda needs: judge(needs, ctx, llm, cap=6)
    except Exception as e:
        print(f"[warn] judgment tier unavailable ({type(e).__name__}: {e})")
        judge_fn = None
```

- [ ] **Step 2: Pass `judge_fn` into `walk`** — change the `walk(...)` call:

```python
        out = walk(page, profile, human, BrowserDeps(),
                   max_steps=args.max_steps, do_submit=args.submit,
                   autonomous=args.autonomous, resume_pdf=resume_pdf, judge_fn=judge_fn)
```

- [ ] **Step 3: Verify import + argparse** —

Run: `PYTHONPATH=src python3 -c "import career_agent.apply"` → no error.
Run: `PYTHONPATH=src python3 -m career_agent.apply --help` → shows `--job-id`.

- [ ] **Step 4: Commit**

```bash
git add src/career_agent/apply.py
git commit -m "feat(career-agent): apply.py wires the judgment tier (--job-id JD grounding) into the walk (Phase E task 5)"
```

---

### Task 6: Full-suite green + live note

**Files:** none (verification).

- [ ] **Step 1: Full repo suite** — `PYTHONPATH=src python3 -m pytest -q` → all green.
- [ ] **Step 2: Record** in the ledger that Phase E judgment tier is implemented; note the live check to run later: a dry-run with `--job-id <id>` on Greenhouse (Formation Bio "What AI tools have you used?") should now carry a drafted answer (source=judgment) instead of escalating, grounded in the résumé; sensitive fields stay blank; nothing submitted.

---

## Self-Review

**Spec coverage:** judge()+helpers → Tasks 1-2; sensitive-never-answered → `_is_sensitive` (Task 1) used in judge (Task 2); option coercion / no-blind-fill → `map_option` (Task 1); free-text via `draft_screening_answer` → Task 2; tier-3 orchestrator → Task 2 (`orchestrator` param); cap → Task 2; walk integration → Task 3; JD by id → Task 4; apply.py wiring → Task 5; validation → Task 6. All covered.

**Type consistency:** `judge(needs_human, ctx, llm, cap=6, orchestrator=None) -> (answered, still_need, flagged)` used identically in Tasks 2/3/5. `JudgmentContext(job, profile_text, research, resume_text)` consistent. `map_option(label, options, profile_text, llm) -> str|None` consistent. `FillDecision` uses the existing 6-field shape (ref, kind, label, value, action, source). `get_job` returns the dict `draft_screening_answer` expects (`job.get("title"/"company"/"description")`).

**Placeholder scan:** no TBD/TODO; every code step has real code. Task 5's argparse note ("place with the others") is an instruction, not a placeholder — the exact `add_argument` line is given.

**Ordering / boundaries:** judge runs AFTER pure `map_screen`; sensitive fields and non-option enum results always land in `still_need` (escalate); `draft_screening_answer` never raises (general_fallback), so judge never raises; the cap bounds calls; dry-run/human-gated-submit unchanged.
