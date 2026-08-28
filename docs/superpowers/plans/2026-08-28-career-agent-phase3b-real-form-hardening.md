# Career Agent Phase 3B — Real-Form Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Phase-3A multi-page walk fill real ATS forms (Greenhouse-verified) correctly and truthfully, staying LLM-free.

**Architecture:** Extend the pure Form-Model matcher and screen-mapper with name-splitting, deterministic standard-answers + option coercion, résumé-upload wiring (via the dashboard's existing render pipeline), and more robust label perception. No new runtime dependencies beyond adding PyYAML to the browser venv.

**Tech Stack:** Python 3.11, Playwright (sync), pytest. Tests: `PYTHONPATH=src python3 -m pytest tests/career_agent` (flat dir, NO `__init__.py`). Browser tests are skip-marked unless `RUN_BROWSER_TESTS=1`, run via `.jd_env`.

## Global Constraints

- **LLM-free.** No qwen3/Claude calls. Ambiguous cases escalate, never guess.
- **Truthful work-authorization.** Never claim authorization the candidate lacks: India→Yes, named non-India country→No, no country named→escalate.
- **Boundaries (Phase 3A):** attestations never auto-ticked; a select/radio is never filled with a non-option value; dry-run never submits; walk stops on any gate whose handler ≠ `proceed` with `stopped_reason=gate:*`.
- **No PII in git.** Résumé PDF renders into gitignored `data/resumes/`.
- **Reuse:** PDF via `job_dashboard.resume.engine.render_layout_pdf` + `resume.render.render_pdf`; upload via the Phase-1 filler `apply_decisions`.
- Branch `career-agent-phase3b` (already created). Commit after each task.

## File Structure

- `src/career_agent/browser/form_model.py` — add purposes + reorder rules (Tasks 1, 2, 6).
- `src/career_agent/orchestrator/profile_resolver.py` — name split + country (Tasks 1, 6).
- `src/career_agent/orchestrator/standard_answers.py` — NEW; deterministic canonical answers (Task 2).
- `src/career_agent/orchestrator/screen_review.py` — standard-answer routing, option coercion, boolean normalize, résumé upload (Tasks 2, 3).
- `src/career_agent/orchestrator/step_engine.py` — thread `resume_pdf` into the walk (Task 3).
- `src/career_agent/apply.py` — render PDF + `--resume-pdf` (Task 3).
- `src/career_agent/browser/perception.py` — robust `labelFor` (Task 4).
- `src/career_agent/memory/candidate_profile.py` — narrow except + warn (Task 5).
- `.jd_env` — add PyYAML (Task 5, non-code step).

---

### Task 1: First/Last name split

**Files:**
- Modify: `src/career_agent/browser/form_model.py` (KNOWN_PURPOSES line 8-15; `_RULES` line 33-34)
- Modify: `src/career_agent/orchestrator/profile_resolver.py`
- Test: `tests/career_agent/test_name_split.py` (new)

**Interfaces:**
- Produces: `guess_purpose("First Name","text")=="first_name"`, `"Last Name"→"last_name"`; `resolve("first_name", profile)`, `resolve("last_name", profile)` return strings derived from `profile.contact`.

- [ ] **Step 1: Write the failing test** — `tests/career_agent/test_name_split.py`

```python
from career_agent.browser.form_model import guess_purpose
from career_agent.memory.candidate_profile import CandidateProfile
from career_agent.orchestrator.profile_resolver import resolve


def test_first_last_purposes_beat_full_name():
    assert guess_purpose("First Name*", "text") == "first_name"
    assert guess_purpose("Given name", "text") == "first_name"
    assert guess_purpose("Last Name", "text") == "last_name"
    assert guess_purpose("Surname", "text") == "last_name"
    assert guess_purpose("Family Name", "text") == "last_name"
    assert guess_purpose("Full Name", "text") == "full_name"  # unchanged


def test_resolve_splits_full_name():
    p = CandidateProfile(contact={"full_name": "Rakshit Singh"})
    assert resolve("first_name", p) == "Rakshit"
    assert resolve("last_name", p) == "Singh"


def test_resolve_prefers_explicit_contact_names():
    p = CandidateProfile(contact={"full_name": "A B C", "first_name": "A", "last_name": "C"})
    assert resolve("first_name", p) == "A"
    assert resolve("last_name", p) == "C"


def test_single_token_name_has_empty_last():
    p = CandidateProfile(contact={"full_name": "Prince"})
    assert resolve("first_name", p) == "Prince"
    assert resolve("last_name", p) is None
```

- [ ] **Step 2: Run to verify it fails** — `PYTHONPATH=src python3 -m pytest tests/career_agent/test_name_split.py -q` → FAIL (`first_name` not a purpose; resolve returns None).

- [ ] **Step 3: form_model.py** — add to `KNOWN_PURPOSES` frozenset: `"first_name", "last_name"`. In `_RULES`, replace the current full_name rule (line 34) with three rules, first/last BEFORE full_name:

```python
    (r"\bfirst name\b|\bgiven name\b|\bforename\b", "first_name"),
    (r"\blast name\b|\bsurname\b|\bfamily name\b", "last_name"),
    (r"\bfull name\b|\byour name\b|\bname\b", "full_name"),
```

- [ ] **Step 4: profile_resolver.py** — add a name-parts helper and branch. After the imports/`_EDU` block, add:

```python
def _name_parts(contact):
    first, last = contact.get("first_name"), contact.get("last_name")
    if first or last:
        return (first or "", last or "")
    toks = (contact.get("full_name") or "").split()
    return (toks[0] if toks else "", " ".join(toks[1:]))
```

In `resolve`, before the `contact.get` fallback, add:

```python
    if purpose in ("first_name", "last_name"):
        first, last = _name_parts(profile.contact)
        return (first if purpose == "first_name" else last) or None
```

- [ ] **Step 5: Run** — `PYTHONPATH=src python3 -m pytest tests/career_agent/test_name_split.py -q` → PASS. Then full career_agent suite green.

- [ ] **Step 6: Commit**

```bash
git add src/career_agent/browser/form_model.py src/career_agent/orchestrator/profile_resolver.py tests/career_agent/test_name_split.py
git commit -m "feat(career-agent): split first/last name purposes (Phase 3B task 1)"
```

---

### Task 2: Standard answers + option coercion

**Files:**
- Create: `src/career_agent/orchestrator/standard_answers.py`
- Modify: `src/career_agent/browser/form_model.py` (KNOWN_PURPOSES; `_RULES` — add sponsorship/prior_contact before work_authorization, narrow work_authorization)
- Modify: `src/career_agent/orchestrator/screen_review.py`
- Test: `tests/career_agent/test_standard_answers.py` (new); extend `tests/career_agent/test_screen_review.py`

**Interfaces:**
- Consumes: `Field`, `FillDecision`, `resolve` (Task 1 signatures unchanged).
- Produces: `standard_answers.answer(purpose:str, label:str) -> str|None`; `map_screen` fills option fields with a coerced option or escalates.

- [ ] **Step 1: Write the failing tests** — `tests/career_agent/test_standard_answers.py`

```python
from career_agent.browser.form_model import guess_purpose
from career_agent.orchestrator.standard_answers import answer


def test_purposes_split_sponsorship_from_authorization():
    assert guess_purpose("Will you require visa sponsorship?", "select") == "visa_sponsorship"
    assert guess_purpose("Are you legally authorized to work in the US?", "select") == "work_authorization"
    assert guess_purpose("Do you have any relatives employed here?", "select") == "prior_contact"


def test_answer_sponsorship_and_contact():
    assert answer("visa_sponsorship", "Will you require sponsorship?") == "Yes"
    assert answer("prior_contact", "Do you know anyone at the company?") == "No"


def test_answer_work_auth_is_jurisdiction_aware():
    assert answer("work_authorization", "Authorized to work in India?") == "Yes"
    assert answer("work_authorization", "Authorized to work in the United States?") == "No"
    assert answer("work_authorization", "Authorized to work in the UK?") == "No"
    assert answer("work_authorization", "Are you legally authorized to work?") is None  # no country -> escalate
```

Extend `tests/career_agent/test_screen_review.py`:

```python
def test_option_coercion_and_escalation():
    from career_agent.browser.form_model import Field
    from career_agent.orchestrator.screen_review import map_screen
    from career_agent.memory.candidate_profile import CandidateProfile
    P = CandidateProfile(contact={})
    yn = ["Yes", "No"]
    spons = Field("#sp", "select", "Will you require visa sponsorship?", True, yn, None, "visa_sponsorship")
    auth_us = Field("#au", "select", "Authorized to work in the US?", True, yn, None, "work_authorization")
    auth_none = Field("#an", "select", "Are you authorized to work?", True, yn, None, "work_authorization")
    no_opt = Field("#x", "select", "Will you require sponsorship?", True, ["Maybe", "Later"], None, "visa_sponsorship")
    decisions, needs = map_screen([spons, auth_us, auth_none, no_opt], P)
    d = {x.ref: x for x in decisions}
    assert d["#sp"].value == "Yes"
    assert d["#au"].value == "No"
    assert "#an" in {f.ref for f in needs}    # no country -> escalate
    assert "#x" in {f.ref for f in needs}     # no matching option -> escalate


def test_boolean_value_normalized_to_yes_no():
    from career_agent.browser.form_model import Field
    from career_agent.orchestrator.screen_review import map_screen
    from career_agent.memory.candidate_profile import CandidateProfile
    P = CandidateProfile(contact={"willing_to_relocate": True})
    f = Field("#r", "select", "Willing to relocate?", True, ["Yes", "No"], None, "willing_to_relocate")
    decisions, needs = map_screen([f], P)
    assert {x.ref: x for x in decisions}["#r"].value == "Yes"
```

- [ ] **Step 2: Run to verify failure** — `PYTHONPATH=src python3 -m pytest tests/career_agent/test_standard_answers.py tests/career_agent/test_screen_review.py -q` → FAIL.

- [ ] **Step 3: form_model.py** — add `"visa_sponsorship", "prior_contact"` to KNOWN_PURPOSES. In `_RULES`, insert these two lines BEFORE the current `work_authorization` rule (line 49) and narrow that rule to drop `sponsor`:

```python
    (r"\bsponsor", "visa_sponsorship"),
    (r"\brelativ|\bknow (anyone|someone)\b|\breferr|\bemployee referral\b"
     r"|\b(contact|connection|relationship)s? (at|with|to)\b|\bfriends? (at|who)\b", "prior_contact"),
    (r"\bauthoriz|\bwork permit\b|\bvisa\b|\beligible to work\b|\blegally (authorized|entitled)\b", "work_authorization"),
```

(Delete the old combined `work_authorization` rule that contained `\bsponsor`.)

- [ ] **Step 4: Create `standard_answers.py`**

```python
"""Deterministic canonical answers for a few standard application questions.
LLM-free. Returns None to signal "escalate to human" — never a guess."""
from __future__ import annotations

import re

_COUNTRY_YES = re.compile(r"\bindia\b", re.I)
_COUNTRY_NO = re.compile(
    r"\b(u\.?\s?s\.?a?\b|united states|america|u\.?k\.?\b|united kingdom|canada|"
    r"australia|germany|singapore|ireland|netherlands|europe|eu)\b", re.I)


def answer(purpose: str, label: str) -> str | None:
    text = label or ""
    if purpose == "visa_sponsorship":
        return "Yes"                      # would need a visa for onsite/relocation
    if purpose == "prior_contact":
        return "No"
    if purpose == "work_authorization":
        if _COUNTRY_YES.search(text):
            return "Yes"
        if _COUNTRY_NO.search(text):
            return "No"
        return None                       # no determinable country -> escalate
    return None
```

- [ ] **Step 5: screen_review.py** — add helpers and route standard purposes + coerce options + normalize booleans. Full new file body:

```python
"""Map a whole screen from the CandidateProfile; collect fields that need the
human. Attestations are never auto-valued; standard questions answered
deterministically; option fields coerced to a real option or escalated."""
from __future__ import annotations

import re

from ..browser.form_model import Field
from ..orchestrator.mapper import FillDecision, _action_for_kind as _action
from ..orchestrator.profile_resolver import resolve
from ..orchestrator import standard_answers

_SELECT_KINDS = {"select", "radio_group"}
_STD_PURPOSES = {"visa_sponsorship", "prior_contact", "work_authorization"}
_YES = {"yes", "y", "true"}
_NO = {"no", "n", "false"}


def _normalize(value):
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return "Yes" if value.strip().lower() == "true" else "No"
    return value


def _coerce_option(value, options):
    v = str(value).strip().lower()
    for o in options:
        if o.strip().lower() == v:
            return o
    toks = _YES if v in _YES else (_NO if v in _NO else None)
    if toks:
        for o in options:
            ol = o.strip().lower()
            if any(re.search(r"\b" + t + r"\b", ol) for t in toks):
                return o
    return None


def _place(f, value, source, decisions, needs_human):
    value = _normalize(value)
    if f.kind in _SELECT_KINDS:
        opt = _coerce_option(value, f.options or [])
        if opt is None:
            needs_human.append(f)
            return
        value = opt
    decisions.append(FillDecision(f.ref, f.kind, f.label, value, _action(f.kind), source))


def map_screen(form, profile, resume_pdf=None):
    decisions, needs_human = [], []
    for f in form:
        if f.kind == "button":
            continue
        if f.purpose == "attestation":
            decisions.append(FillDecision(f.ref, f.kind, f.label, None, "attestation", "flag"))
            continue
        if f.purpose == "resume_upload" or f.kind == "file":
            if resume_pdf:
                decisions.append(FillDecision(f.ref, f.kind, f.label, resume_pdf, "upload", "resume"))
            else:
                needs_human.append(f)
            continue
        if f.purpose in _STD_PURPOSES:
            ans = standard_answers.answer(f.purpose, f.label)
            if ans is None:
                needs_human.append(f)
            else:
                _place(f, ans, "standard", decisions, needs_human)
            continue
        value = resolve(f.purpose, profile) if f.purpose else None
        if value is not None:
            _place(f, value, "resume", decisions, needs_human)
        elif f.required or (f.purpose is None and f.kind in ("text", "textarea")):
            needs_human.append(f)
    return decisions, needs_human


def apply_answers(needs_human, answers):
    out = []
    for f in needs_human:
        v = answers.get(f.ref)
        if v is None:
            continue
        out.append(FillDecision(f.ref, f.kind, f.label, v, _action(f.kind), "human"))
    return out
```

Note: `resume_pdf` defaults to None so all existing `map_screen(form, profile)` callers/tests keep working. The file-field branch escalates when no résumé is set — but existing Phase-3A tests pass `Field`s of kind text/select only, so they are unaffected.

- [ ] **Step 6: Run** — the two test files → PASS. Then full career_agent suite green (watch for any Phase-3A screen_review test that assumed a select value filled verbatim; there are none — Phase-3A escalated non-option values, which coercion now handles or still escalates).

- [ ] **Step 7: Commit**

```bash
git add src/career_agent/orchestrator/standard_answers.py src/career_agent/orchestrator/screen_review.py src/career_agent/browser/form_model.py tests/career_agent/test_standard_answers.py tests/career_agent/test_screen_review.py
git commit -m "feat(career-agent): standard answers + option coercion (Phase 3B task 2)"
```

---

### Task 3: Résumé upload in the walk

**Files:**
- Modify: `src/career_agent/orchestrator/step_engine.py` (`walk` signature + `map_screen` call)
- Modify: `src/career_agent/apply.py` (render PDF, `--resume-pdf`, pass into walk)
- Test: extend `tests/career_agent/test_step_engine.py`; verify filler upload support
- Check: `src/career_agent/browser/filler.py` — confirm `apply_decisions` handles `action=="upload"` via `set_input_files` (read before relying on it).

**Interfaces:**
- Consumes: `map_screen(form, profile, resume_pdf)` (Task 2).
- Produces: `walk(page, profile, human, deps, ..., resume_pdf=None)`.

- [ ] **Step 1: Read the filler** — `src/career_agent/browser/filler.py`. Confirm an `upload` action path exists (`page.set_input_files(ref, path)`). If it does NOT, add one: for a decision with `action=="upload"`, call `page.set_input_files(decision.ref, decision.value)`; otherwise keep behavior. (This is part of this task's implementation, tested via the browser test in Task-3 Step 5.)

- [ ] **Step 2: Write the failing test** — extend `tests/career_agent/test_step_engine.py`:

```python
def test_resume_pdf_threads_to_upload_decision():
    from career_agent.browser.form_model import Field
    from career_agent.orchestrator.step_engine import walk
    from career_agent.memory.candidate_profile import CandidateProfile
    s1 = [Field("#cv", "file", "Attach resume", False, [], None, "resume_upload"),
          Field("#c", "button", "Submit application", False, [], None, None)]
    deps = Deps([s1])
    walk(object(), CandidateProfile(), Human(), deps, do_submit=True, autonomous=True,
         resume_pdf="/tmp/cv.pdf")
    uploads = [d for batch in deps.filled for d in batch if d.action == "upload"]
    assert uploads and uploads[0].value == "/tmp/cv.pdf"
```

(`Deps`, `Human` already defined at the top of the file.)

- [ ] **Step 3: Run to verify failure** — `PYTHONPATH=src python3 -m pytest tests/career_agent/test_step_engine.py::test_resume_pdf_threads_to_upload_decision -q` → FAIL (`walk` has no `resume_pdf` kwarg).

- [ ] **Step 4: step_engine.py** — add `resume_pdf=None` to `walk`'s signature (after `on_link=None`) and change the map_screen call:

```python
        decisions, needs = map_screen(form, profile, resume_pdf)
```

- [ ] **Step 5: apply.py** — render the PDF and thread it in. Add the arg and rendering (inside `main`, after `profile = load_candidate_profile(...)`):

```python
    ap.add_argument("--resume-pdf", default=None)
    ...
    resume_pdf = args.resume_pdf
    if resume_pdf is None:
        try:
            from pathlib import Path
            from job_dashboard.db import get_resume_layout
            from job_dashboard.resume.engine import render_layout_pdf
            from job_dashboard.resume.render import render_pdf
            from job_dashboard.resume.segments import load_segments
            rec = get_resume_layout(conn, args.resume_version)
            out_dir = Path(args.db).parent / "resumes"
            out_dir.mkdir(parents=True, exist_ok=True)
            res = render_layout_pdf(rec["layout"], segments=load_segments(),
                                    render_pdf=render_pdf, out_dir=out_dir)
            resume_pdf = str(res["pdf_path"])
        except Exception as e:
            print(f"[warn] résumé render unavailable ({type(e).__name__}: {e}); file fields will escalate")
            resume_pdf = None
    ...
    out = walk(page, profile, human, BrowserDeps(), max_steps=args.max_steps,
               do_submit=args.submit, autonomous=args.autonomous, resume_pdf=resume_pdf)
```

- [ ] **Step 6: Run** — the new unit test → PASS; full career_agent suite green. (Browser upload is exercised live in the Task-9 validation dry-run, not a skip-marked unit test.)

- [ ] **Step 7: Commit**

```bash
git add src/career_agent/orchestrator/step_engine.py src/career_agent/apply.py src/career_agent/browser/filler.py tests/career_agent/test_step_engine.py
git commit -m "feat(career-agent): résumé upload threaded through the walk (Phase 3B task 3)"
```

---

### Task 4: Robust label perception (browser test)

**Files:**
- Modify: `src/career_agent/browser/perception.py` (`_INPUT_JS` `labelFor`)
- Test: `tests/career_agent/test_label_perception_browser.py` (new, skip unless `RUN_BROWSER_TESTS=1`) + fixture `tests/career_agent/fixtures/greenhouse_labels.html`

**Interfaces:**
- Produces: `snapshot_form(page)` returns non-empty labels for Greenhouse-style inputs (label as sibling / `aria-labelledby`).

- [ ] **Step 1: Fixture** — `tests/career_agent/fixtures/greenhouse_labels.html`:

```html
<!doctype html><html><body>
  <div class="field"><div id="lbl_ct">Country*</div>
    <input type="text" aria-labelledby="lbl_ct"></div>
  <div class="field"><label class="sep">Highest level of education*</label>
    <input type="text"></div>
  <div class="field"><input type="text" placeholder="LinkedIn Profile"></div>
</body></html>
```

- [ ] **Step 2: Write the failing test** — `tests/career_agent/test_label_perception_browser.py`:

```python
import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1",
                                reason="set RUN_BROWSER_TESTS=1 to run")


def _url(name):
    return (Path(__file__).parent / "fixtures" / name).resolve().as_uri()


def test_greenhouse_style_labels_are_captured():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.goto(_url("greenhouse_labels.html"))
        labels = [f.label for f in snapshot_form(page) if f.kind != "button"]
        b.close()
    assert any("Country" in l for l in labels)
    assert any("education" in l.lower() for l in labels)
    assert any("LinkedIn" in l for l in labels)
    assert "" not in labels          # no empty-label inputs
```

- [ ] **Step 3: Run to verify failure** — `source .jd_env/bin/activate && RUN_BROWSER_TESTS=1 PYTHONPATH=src python3 -m pytest tests/career_agent/test_label_perception_browser.py -q` → FAIL (aria-labelledby / sibling / placeholder not resolved → empty labels).

- [ ] **Step 4: perception.py** — extend `labelFor` in `_INPUT_JS`. Replace the final `return (el.getAttribute('aria-label') || el.name || '').trim();` with a chain that also tries `aria-labelledby`, a preceding sibling / ancestor leading label, and `placeholder`:

```javascript
    const al = el.getAttribute('aria-label');
    if (al) return al.trim();
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const t = lb.split(/\s+/).map(id => {
        const n = document.getElementById(id); return n ? n.innerText : '';
      }).join(' ').trim();
      if (t) return t;
    }
    // a label-like element just before the input, or the field container's leading text
    let prev = el.previousElementSibling;
    while (prev) {
      const t = (prev.innerText || '').trim();
      if (t) return t;
      prev = prev.previousElementSibling;
    }
    const container = el.closest('div,section,fieldset,li');
    if (container) {
      const lbl = container.querySelector('label,legend,.label,[class*=label]');
      if (lbl && (lbl.innerText || '').trim()) return lbl.innerText.trim();
    }
    return (el.name || el.getAttribute('placeholder') || '').trim();
```

- [ ] **Step 5: Run** — the browser test → PASS. Then re-run the FULL browser suite (`RUN_BROWSER_TESTS=1`) incl. `test_walk_browser.py` to confirm no regression in label handling for the existing fixtures.

- [ ] **Step 6: Commit**

```bash
git add src/career_agent/browser/perception.py tests/career_agent/test_label_perception_browser.py tests/career_agent/fixtures/greenhouse_labels.html
git commit -m "feat(career-agent): robust label perception for Greenhouse-style forms (Phase 3B task 4)"
```

---

### Task 5: Education / YAML robustness

**Files:**
- Modify: `src/career_agent/memory/candidate_profile.py` (`load_candidate_profile` except)
- Test: extend `tests/career_agent/test_candidate_profile.py`
- Non-code: `.jd_env/bin/pip install pyyaml`

**Interfaces:**
- Produces: `load_candidate_profile` narrows its except and warns; still returns a profile (empty education) when segments are unavailable.

- [ ] **Step 1: Write the failing test** — extend `tests/career_agent/test_candidate_profile.py`:

```python
def test_missing_segments_warns_not_crashes(monkeypatch, capsys):
    import career_agent.memory.candidate_profile as cp

    class FakeConn:
        pass

    monkeypatch.setattr(cp, "get_resume_layout", lambda conn, v: {"layout": []}, raising=False)
    import job_dashboard.resume.segments as seg

    def boom(*a, **k):
        raise ImportError("No module named 'yaml'")

    monkeypatch.setattr(seg, "load_segments", boom)
    p = cp.load_candidate_profile(FakeConn())
    assert p.education == []
    assert "education unavailable" in capsys.readouterr().err.lower()
```

(`get_resume_layout` is imported lazily inside `load_candidate_profile`; the test also patches the module attribute — set it at module scope so the lazy `from job_dashboard.db import get_resume_layout` still resolves. If the lazy import defeats the monkeypatch, change `load_candidate_profile` to `import job_dashboard.db as _db; layout = _db.get_resume_layout(...)` and patch `_db.get_resume_layout` — do whichever the run proves necessary; the assertion on warning + empty education is the contract.)

- [ ] **Step 2: Run to verify failure** — `PYTHONPATH=src python3 -m pytest tests/career_agent/test_candidate_profile.py::test_missing_segments_warns_not_crashes -q` → FAIL (no warning emitted; broad except swallows silently).

- [ ] **Step 3: candidate_profile.py** — narrow the except in `load_candidate_profile`:

```python
    try:
        from job_dashboard.resume.segments import load_segments
        prof.education = education_from_segments(load_segments())
    except (ImportError, FileNotFoundError) as e:
        import sys
        print(f"[warn] education unavailable ({type(e).__name__}: {e})", file=sys.stderr)
    return prof
```

- [ ] **Step 4: Run** — the new test → PASS; full career_agent suite green.

- [ ] **Step 5: Install PyYAML in the browser venv**

```bash
.jd_env/bin/pip install pyyaml
.jd_env/bin/python -c "import yaml; print('yaml', yaml.__version__)"
```

- [ ] **Step 6: Commit** (code only; `.jd_env` is gitignored)

```bash
git add src/career_agent/memory/candidate_profile.py tests/career_agent/test_candidate_profile.py
git commit -m "fix(career-agent): surface (not swallow) missing-segment education load (Phase 3B task 5)"
```

---

### Task 6: Country mapping

**Files:**
- Modify: `src/career_agent/browser/form_model.py` (KNOWN_PURPOSES; `_RULES` — country before location)
- Modify: `src/career_agent/orchestrator/profile_resolver.py`
- Test: extend `tests/career_agent/test_name_split.py` (or a small `test_country.py`)

**Interfaces:**
- Produces: `guess_purpose("Country","text")=="country"`; `resolve("country", profile)` → trailing token of `contact["location"]`.

- [ ] **Step 1: Write the failing test** — new `tests/career_agent/test_country.py`:

```python
from career_agent.browser.form_model import guess_purpose
from career_agent.memory.candidate_profile import CandidateProfile
from career_agent.orchestrator.profile_resolver import resolve


def test_country_purpose_and_resolution():
    assert guess_purpose("Country*", "text") == "country"
    p = CandidateProfile(contact={"location": "Mumbai, India"})
    assert resolve("country", p) == "India"


def test_country_without_comma_escalates():
    p = CandidateProfile(contact={"location": "Remote"})
    assert resolve("country", p) is None  # can't determine a country
```

- [ ] **Step 2: Run to verify failure** → FAIL.

- [ ] **Step 3: form_model.py** — add `"country"` to KNOWN_PURPOSES. In `_RULES`, add BEFORE the location rule (line 55):

```python
    (r"\bcountry\b", "country"),
```

- [ ] **Step 4: profile_resolver.py** — in `resolve`, add before the `contact.get` fallback:

```python
    if purpose == "country":
        loc = profile.contact.get("location") or ""
        return loc.split(",")[-1].strip() if "," in loc else None
```

- [ ] **Step 5: Run** — `test_country.py` → PASS; full career_agent suite green.

- [ ] **Step 6: Commit**

```bash
git add src/career_agent/browser/form_model.py src/career_agent/orchestrator/profile_resolver.py tests/career_agent/test_country.py
git commit -m "feat(career-agent): map Country field from location (Phase 3B task 6)"
```

---

### Task 7: Full-suite green + live re-validation

**Files:** none (verification).

- [ ] **Step 1: Full repo suite** — `PYTHONPATH=src python3 -m pytest -q` → all green.
- [ ] **Step 2: Browser suite** — `source .jd_env/bin/activate && RUN_BROWSER_TESTS=1 PYTHONPATH=src python3 -m pytest tests/career_agent -q` → green (walk + label fixtures).
- [ ] **Step 3: Live dry-run** — re-run the instrumented Greenhouse dry-run (scratchpad `dryrun_trace.py`, Formation Bio) and confirm against the spec's live-validation checklist: First/Last split; sponsorship=Yes; work-auth per-jurisdiction or escalated; résumé attached (upload decision); no empty-label escalations; education present; `reached_submit_dry_run`; nothing submitted. Record the trace outcome in the ledger.

---

## Self-Review

**Spec coverage:** Component 1→Task 1; 2→Task 2; 3→Task 3; 4→Task 4; 5→Task 5; 6→Task 6; live validation→Task 7. All covered.

**Type consistency:** `map_screen(form, profile, resume_pdf=None)` defined in Task 2, consumed in Task 3 (`walk` passes 3rd positional). `standard_answers.answer(purpose, label)` defined Task 2, used in Task 2 screen_review. `_name_parts` Task 1. `resolve` gains `first_name`/`last_name`/`country` branches (Tasks 1, 6) — signature unchanged. New purposes added to KNOWN_PURPOSES in the same tasks that add their rules.

**Placeholder scan:** Task 3 Step 1 (read filler, add upload path if missing) and Task 5 Step 1 (monkeypatch caveat) are the only conditional steps; both state the concrete contract to satisfy, not "figure it out". No TBD/TODO.

**Ordering risk:** every new `_RULES` entry is placed BEFORE the more general rule it must beat (first/last before full_name; sponsorship/prior_contact before work_authorization; country before location) — matcher is first-hit-wins.
