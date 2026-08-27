# Career Agent — Phase 3A: Multi-Page Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An orchestrator that walks a multi-screen job application from a target URL — perceive → fill from a résumé-derived profile → escalate unknowns over Telegram → clear gates → advance → repeat — stopping at an approval-gated (or autonomous) submit.

**Architecture:** A plain Python step-loop (each iteration = one screen), reusing Phase 1/2 (perception, mapper, filler, gate_probe, remote-solve, human_loop). Fill data comes from a `CandidateProfile` extracted from the saved résumé version `Rakshit_Singh_draft1` (`resume_layouts` blocks) + `application_profile`. No LangGraph yet (that's sub-project B).

**Tech Stack:** Python 3.11 · reuse `job_dashboard` (résumé layout store, Ollama client) · Playwright (via Phase 1/2) · pytest.

## Global Constraints

- **No evasion.** Gates are detected and either human-solved (captcha → Phase-2 remote-solve) or escalated (OTP, Cloudflare, etc.) — never bypassed.
- **Attestations never auto-answered** — always surfaced to the human.
- **Submit is approval-gated by default**; autonomous only when explicitly enabled (`autonomous=True`).
- **Max-steps cap** (default 15) — the loop can never run away.
- **The only LLM use is bounded résumé→JSON extraction** on local qwen3:14b (injected/faked in tests). No judgment-tier answering of novel questions — those escalate.
- **PII stays local:** the CandidateProfile cache is written outside the repo / gitignored, never committed.
- **File hygiene:** every file < 500 lines. Tests under `tests/career_agent/`, flat, **no `__init__.py`** (it shadows the real package).
- Reuse, don't fork: `from job_dashboard.db import get_resume_layout`; `from job_dashboard.apply.store import get_application_profile`.

## Interfaces carried from Phase 1/2

- `Field` (`browser/form_model.py`): `ref, kind, label, required, options, group, purpose`.
- `FillDecision` (`orchestrator/mapper.py`): `ref, kind, label, value, action, source`; `map_fields(form, profile, resume_path) -> list[FillDecision]`.
- `snapshot_form(page) -> list[Field]`, `classify_gate(page) -> str`, `HANDLERS`.
- `HumanLoop` (`integrations/human_loop.py`): `approve(card)->bool`, `remote_solve(page, gate, on_link)->bool`.

---

### Task 1: CandidateProfile types + résumé-layout extraction

**Files:**
- Create: `src/career_agent/memory/candidate_profile.py`
- Test: `tests/career_agent/test_candidate_profile.py`

**Interfaces:**
- Produces: dataclasses `Experience{company, title, start, end, bullets:list}`, `Education{school, degree, field, start, end}`, `CandidateProfile{contact:dict, experiences:list, education:list, skills:list}`.
- `blocks_to_profile(blocks: list[dict], contact: dict, split=None) -> CandidateProfile` — pure; groups experience blocks by their `group` (company), reads the `roleHeader` block's title for role/dates, collects non-header bullets, reads skills blocks into `skills`, skips `excluded: True`. `split(title) -> dict` is an optional callable (the qwen3 title-splitter) used only when a `roleHeader` title can't be parsed by rule; defaults to a rule-based splitter.
- `load_candidate_profile(conn, version="Rakshit_Singh_draft1", contact=None, split=None) -> CandidateProfile` — loads the layout via `get_resume_layout` and calls `blocks_to_profile`.

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_candidate_profile.py
from career_agent.memory.candidate_profile import blocks_to_profile, CandidateProfile

BLOCKS = [
    {"kind": "experience", "title": "Data Scientist, Tata AIG — July 2023 – Present, Mumbai",
     "bullets": [], "group": "Tata AIG", "roleHeader": True, "excluded": False},
    {"kind": "experience", "title": "Health Fraud Pipeline",
     "bullets": ["Built fraud models, ROC>85."], "group": "Tata AIG",
     "roleHeader": False, "excluded": False},
    {"kind": "experience", "title": "Send Time Optimization",
     "bullets": ["skip me"], "group": "Tata AIG", "roleHeader": False, "excluded": True},
    {"kind": "skills", "title": "Programming",
     "bullets": ["**Programming**: Python, SQL, AWS"], "excluded": False},
]

def test_groups_experience_by_company_and_reads_roleheader():
    p = blocks_to_profile(BLOCKS, contact={"full_name": "Rakshit"})
    assert isinstance(p, CandidateProfile)
    assert p.contact["full_name"] == "Rakshit"
    tata = [e for e in p.experiences if e.company == "Tata AIG"]
    assert len(tata) == 1
    e = tata[0]
    assert e.title == "Data Scientist"
    assert e.start == "July 2023" and e.end == "Present"
    assert "Built fraud models, ROC>85." in e.bullets
    assert all("skip me" not in b for b in e.bullets)   # excluded block dropped

def test_skills_parsed():
    p = blocks_to_profile(BLOCKS, contact={})
    assert "Python" in p.skills and "AWS" in p.skills
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_candidate_profile.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `candidate_profile.py`**

```python
# src/career_agent/memory/candidate_profile.py
"""CandidateProfile: structured facts extracted from a saved résumé version
(resume_layouts blocks) + application_profile. Rule-based; a `split` callable
(qwen3:14b) is used only for role-header titles a rule can't parse."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Experience:
    company: str
    title: str = ""
    start: str = ""
    end: str = ""
    bullets: list = field(default_factory=list)


@dataclass
class Education:
    school: str
    degree: str = ""
    field: str = ""
    start: str = ""
    end: str = ""


@dataclass
class CandidateProfile:
    contact: dict = field(default_factory=dict)
    experiences: list = field(default_factory=list)
    education: list = field(default_factory=list)
    skills: list = field(default_factory=list)


# "Role, Company — start – end, location"  (em dash or hyphen; en dash range)
_ROLE_RE = re.compile(
    r"^(?P<title>[^,]+?),\s*(?P<company>[^—\-]+?)\s*[—\-]\s*"
    r"(?P<start>[^–\-]+?)\s*[–\-]\s*(?P<end>[^,]+)", re.U)


def _rule_split(title: str) -> dict:
    m = _ROLE_RE.match(title.strip())
    if not m:
        return {}
    return {k: m.group(k).strip() for k in ("title", "company", "start", "end")}


def _skills_from(bullet: str) -> list:
    # "**Programming**: Python, SQL, AWS" -> [Python, SQL, AWS]
    tail = bullet.split(":", 1)[1] if ":" in bullet else bullet
    return [s.strip(" *") for s in re.split(r"[,;]", tail) if s.strip(" *")]


def blocks_to_profile(blocks, contact, split=None) -> CandidateProfile:
    split = split or _rule_split
    prof = CandidateProfile(contact=dict(contact or {}))
    by_company: dict = {}
    for b in blocks:
        if b.get("excluded"):
            continue
        kind = b.get("kind")
        if kind == "skills":
            for bl in b.get("bullets", []):
                prof.skills.extend(_skills_from(bl))
        elif kind == "experience":
            company = b.get("group") or "(unknown)"
            exp = by_company.get(company)
            if exp is None:
                exp = Experience(company=company)
                by_company[company] = exp
                prof.experiences.append(exp)
            if b.get("roleHeader"):
                parts = split(b.get("title", ""))
                if parts:
                    exp.title = parts.get("title", exp.title)
                    exp.company = parts.get("company", exp.company)
                    exp.start = parts.get("start", exp.start)
                    exp.end = parts.get("end", exp.end)
            else:
                exp.bullets.extend(b.get("bullets", []))
    # de-dup skills, preserve order
    seen = set()
    prof.skills = [s for s in prof.skills if not (s in seen or seen.add(s))]
    return prof


def load_candidate_profile(conn, version="Rakshit_Singh_draft1", contact=None, split=None):
    from job_dashboard.db import get_resume_layout
    layout = get_resume_layout(conn, version)
    blocks = (layout or {}).get("layout", [])
    return blocks_to_profile(blocks, contact or {}, split=split)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_candidate_profile.py -v`
Expected: PASS (2 passed). If the role-header regex doesn't split the sample title, adjust `_ROLE_RE` until `test_groups_experience_by_company_and_reads_roleheader` passes (the title uses an em dash `—` before dates and an en dash `–` in the range).

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/memory/candidate_profile.py tests/career_agent/test_candidate_profile.py
git commit -m "feat(career-agent): CandidateProfile from saved résumé layout blocks"
```

---

### Task 2: Extend the purpose vocabulary (résumé-driven fields)

**Files:**
- Modify: `src/career_agent/browser/form_model.py` (KNOWN_PURPOSES + `_RULES`)
- Test: `tests/career_agent/test_form_model_phase3.py`

**Interfaces:**
- `KNOWN_PURPOSES` gains: `employer, job_title, start_date, end_date, degree, school, field_of_study, gpa, skills, summary`.
- `guess_purpose(label, kind)` recognizes those labels.

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_form_model_phase3.py
from career_agent.browser.form_model import guess_purpose, KNOWN_PURPOSES

def test_experience_and_education_purposes():
    assert guess_purpose("Employer", "text") == "employer"
    assert guess_purpose("Company Name", "text") == "employer"
    assert guess_purpose("Job Title", "text") == "job_title"
    assert guess_purpose("Start Date", "text") == "start_date"
    assert guess_purpose("End Date", "text") == "end_date"
    assert guess_purpose("University / School", "text") == "school"
    assert guess_purpose("Degree", "text") == "degree"
    assert guess_purpose("Field of Study", "text") == "field_of_study"
    assert guess_purpose("Key Skills", "textarea") == "skills"

def test_new_purposes_are_known():
    for lbl, kind in [("Employer","text"), ("Degree","text"), ("Key Skills","textarea")]:
        assert guess_purpose(lbl, kind) in KNOWN_PURPOSES
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_form_model_phase3.py -v`
Expected: FAIL — new purposes not recognized.

- [ ] **Step 3: Extend `form_model.py`**

Add to `KNOWN_PURPOSES` the ten new strings. Add rules to `_RULES` (most-specific-first, BEFORE the generic `experience`/`name` rules so e.g. "Company Name" hits `employer` not `full_name`):

```python
    (r"\bemployer\b|\bcompany name\b|\bcompany\b|\borganization\b", "employer"),
    (r"\bjob title\b|\bposition title\b|\brole\b|\btitle\b", "job_title"),
    (r"\bstart date\b|\bfrom\b(?!.*name)|\bdate from\b", "start_date"),
    (r"\bend date\b|\bto\b(?=\s|$)|\bdate to\b", "end_date"),
    (r"\bfield of study\b|\bmajor\b|\bspecial", "field_of_study"),
    (r"\bdegree\b|\bqualification\b", "degree"),
    (r"\buniversity\b|\bschool\b|\bcollege\b|\binstitution\b", "school"),
    (r"\bgpa\b|\bgrade\b|\bcgpa\b|\bpercentage\b", "gpa"),
    (r"\bskills?\b|\bkey skills\b|\btechnolog", "skills"),
    (r"\bsummary\b|\babout you\b|\bprofile summary\b", "summary"),
```

Place these near the top of `_RULES` (before the existing `full_name`/`experience` lines) so the more specific job/education labels win.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_form_model_phase3.py tests/career_agent/test_form_model.py -v`
Expected: PASS (both files — Phase-1 purpose tests must stay green; if "Full name" now mis-hits `employer`/`job_title`, tighten the new rules to require the specific words and keep `\bfull name\b` ahead of `\btitle\b`).

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/browser/form_model.py tests/career_agent/test_form_model_phase3.py
git commit -m "feat(career-agent): résumé-oriented purposes (employer/title/dates/degree/school/skills)"
```

---

### Task 3: Profile resolver — fill scalar fields from CandidateProfile

**Files:**
- Create: `src/career_agent/orchestrator/profile_resolver.py`
- Test: `tests/career_agent/test_profile_resolver.py`

**Interfaces:**
- Consumes: `CandidateProfile` (Task 1).
- Produces: `resolve(purpose: str, profile: CandidateProfile, index: int = 0) -> object|None` — returns the value for a purpose, using `experiences[index]` / `education[index]` for repeating fields: `employer`→`experiences[i].company`, `job_title`→`.title`, `start_date`→`.start`, `end_date`→`.end`, `school`/`degree`/`field_of_study`→`education[i]`, `skills`→`", ".join(skills)`, contact purposes (`full_name`,`email`,…)→`contact[...]`. Missing → None.

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_profile_resolver.py
from career_agent.memory.candidate_profile import CandidateProfile, Experience, Education
from career_agent.orchestrator.profile_resolver import resolve

P = CandidateProfile(
    contact={"full_name": "Rakshit", "email": "r@x.com"},
    experiences=[Experience("Tata AIG", "Data Scientist", "July 2023", "Present", ["b"]),
                 Experience("OYO", "Intern", "May 2022", "Jul 2022", [])],
    education=[Education("IIT", "B.Tech", "CS", "2018", "2022")],
    skills=["Python", "SQL"])

def test_scalar_and_indexed_resolution():
    assert resolve("full_name", P) == "Rakshit"
    assert resolve("employer", P, 0) == "Tata AIG"
    assert resolve("job_title", P, 0) == "Data Scientist"
    assert resolve("employer", P, 1) == "OYO"
    assert resolve("school", P, 0) == "IIT"
    assert resolve("degree", P, 0) == "B.Tech"
    assert resolve("skills", P) == "Python, SQL"

def test_missing_returns_none():
    assert resolve("employer", P, 5) is None
    assert resolve("gpa", P, 0) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_profile_resolver.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `profile_resolver.py`**

```python
# src/career_agent/orchestrator/profile_resolver.py
"""Resolve a field purpose to a value from the CandidateProfile, using an index
for repeating experience/education rows."""
from __future__ import annotations

_EXP = {"employer": "company", "job_title": "title", "start_date": "start", "end_date": "end"}
_EDU = {"school": "school", "degree": "degree", "field_of_study": "field"}


def resolve(purpose, profile, index=0):
    if purpose in _EXP:
        if 0 <= index < len(profile.experiences):
            return getattr(profile.experiences[index], _EXP[purpose]) or None
        return None
    if purpose in _EDU:
        if 0 <= index < len(profile.education):
            return getattr(profile.education[index], _EDU[purpose]) or None
        return None
    if purpose == "skills":
        return ", ".join(profile.skills) if profile.skills else None
    return profile.contact.get(purpose) or None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_profile_resolver.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/orchestrator/profile_resolver.py tests/career_agent/test_profile_resolver.py
git commit -m "feat(career-agent): profile resolver (purpose -> CandidateProfile value, indexed)"
```

---

### Task 4: Screen mapper — fill a screen from CandidateProfile, collect needs_human

**Files:**
- Create: `src/career_agent/orchestrator/screen_review.py`
- Test: `tests/career_agent/test_screen_review.py`

**Interfaces:**
- Consumes: `Field` (Phase 1), `CandidateProfile`, `resolve` (Task 3), `guess_purpose`.
- Produces: `map_screen(form: list[Field], profile: CandidateProfile) -> tuple[list[FillDecision], list[Field]]` — returns `(decisions, needs_human)`. For each field: attestation → attestation decision (never valued); a purpose that `resolve`s to a value → fill/select decision; a **required** field with no value, or any free-text field whose purpose is `None` (a novel question) → `needs_human`. Non-required unmapped fields are skipped.
- `apply_answers(needs_human: list[Field], answers: dict[str,str]) -> list[FillDecision]` — turns human-provided `{ref: value}` into fill decisions.

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_screen_review.py
from career_agent.browser.form_model import Field
from career_agent.memory.candidate_profile import CandidateProfile, Experience
from career_agent.orchestrator.screen_review import map_screen, apply_answers

P = CandidateProfile(contact={"full_name": "Rakshit", "email": "r@x.com"},
                     experiences=[Experience("Tata AIG", "Data Scientist", "2023", "Present", [])],
                     skills=["Python"])

def _f(ref, label, purpose, required=False, kind="text"):
    return Field(ref, kind, label, required, [], None, purpose)

def test_fills_known_and_flags_unknown():
    form = [_f("#n", "Full name", "full_name"),
            _f("#emp", "Employer", "employer"),
            _f("#q", "Why do you want this job?", None, required=True, kind="textarea"),
            _f("#missing", "Portfolio URL", "portfolio_url", required=True)]
    decisions, needs = map_screen(form, P)
    d = {x.ref: x for x in decisions}
    assert d["#n"].value == "Rakshit" and d["#emp"].value == "Tata AIG"
    refs = {f.ref for f in needs}
    assert "#q" in refs          # novel required question -> human
    assert "#missing" in refs    # required, no profile value -> human

def test_apply_answers():
    needs = [_f("#q", "Why?", None, required=True, kind="textarea")]
    decisions = apply_answers(needs, {"#q": "Because I love ML."})
    assert decisions[0].value == "Because I love ML." and decisions[0].action == "fill"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_screen_review.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `screen_review.py`**

```python
# src/career_agent/orchestrator/screen_review.py
"""Map a whole screen from the CandidateProfile; collect fields that need the
human. Attestations are never auto-valued; novel required questions escalate."""
from __future__ import annotations

from ..browser.form_model import Field
from ..orchestrator.mapper import FillDecision
from ..orchestrator.profile_resolver import resolve

_SELECT_KINDS = {"select", "radio_group"}


def _action(kind):
    return "select" if kind == "select" else ("check_group" if kind == "radio_group" else "fill")


def map_screen(form, profile):
    decisions, needs_human = [], []
    for f in form:
        if f.purpose == "attestation":
            decisions.append(FillDecision(f.ref, f.kind, f.label, None, "attestation", "flag"))
            continue
        value = resolve(f.purpose, profile) if f.purpose else None
        if value is not None:
            if f.kind in _SELECT_KINDS and value not in (f.options or []):
                needs_human.append(f)          # can't safely pick an option
                continue
            decisions.append(FillDecision(f.ref, f.kind, f.label, value, _action(f.kind), "resume"))
        elif f.required or (f.purpose is None and f.kind in ("text", "textarea")):
            needs_human.append(f)              # required-unknown or novel question
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_screen_review.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/orchestrator/screen_review.py tests/career_agent/test_screen_review.py
git commit -m "feat(career-agent): screen mapper (fill from résumé, escalate unknowns)"
```

---

### Task 5: Advance control + screen-signature change detection

**Files:**
- Create: `src/career_agent/orchestrator/advance.py`
- Test: `tests/career_agent/test_advance.py`

**Interfaces:**
- `screen_signature(url: str, form: list[Field]) -> tuple` — `(url_path, frozenset(field labels))`; deterministic.
- `changed(before: tuple, after: tuple) -> bool` — True if signatures differ.
- `pick_advance_label(form, is_last: bool) -> str|None` — chooses the control name to click: prefers Next/Continue/Save and continue/Review when more steps expected; Submit/Apply when `is_last`; returns None if none present. (Uses field labels + a fixed candidate list; the browser-bound click lives in the step engine.)
- `ADVANCE_NAMES`, `SUBMIT_NAMES`, `NEVER_NAMES` (Back/Cancel/Previous).

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_advance.py
from career_agent.browser.form_model import Field
from career_agent.orchestrator.advance import screen_signature, changed, pick_advance_label

def _f(label): return Field("#"+label, "text", label, False, [], None, None)

def test_signature_changes_when_labels_change():
    a = screen_signature("http://x/step1", [_f("Email")])
    b = screen_signature("http://x/step1", [_f("First name"), _f("Last name")])
    assert changed(a, b) is True
    assert changed(a, a) is False

def test_pick_advance_prefers_continue_then_submit():
    names = ["Continue", "Cancel"]
    form = [Field("#b", "button", n, False, [], None, None) for n in names]
    assert pick_advance_label(form, is_last=False) == "Continue"
    subm = [Field("#s", "button", "Submit application", False, [], None, None)]
    assert pick_advance_label(subm, is_last=True) == "Submit application"

def test_never_returns_back_or_cancel():
    form = [Field("#b", "button", "Back", False, [], None, None)]
    assert pick_advance_label(form, is_last=False) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_advance.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `advance.py`**

```python
# src/career_agent/orchestrator/advance.py
"""Screen-signature change detection + choosing the advance control's label.
Pure; the actual click is done by the step engine via Playwright get_by_role."""
from __future__ import annotations

from urllib.parse import urlparse

ADVANCE_NAMES = ["save and continue", "continue", "next", "review", "save & continue"]
SUBMIT_NAMES = ["submit application", "submit", "apply", "finish", "confirm"]
NEVER_NAMES = ["back", "cancel", "previous", "logout", "sign out"]


def screen_signature(url, form):
    return (urlparse(url).path, frozenset(f.label.strip().lower() for f in form if f.label))


def changed(before, after):
    return before != after


def _labels(form):
    return [f.label.strip() for f in form if f.label]


def pick_advance_label(form, is_last):
    labels = _labels(form)
    lowered = {l.lower(): l for l in labels}
    order = (SUBMIT_NAMES + ADVANCE_NAMES) if is_last else (ADVANCE_NAMES + SUBMIT_NAMES)
    for cand in order:
        for low, orig in lowered.items():
            if cand in low and not any(bad in low for bad in NEVER_NAMES):
                return orig
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_advance.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/orchestrator/advance.py tests/career_agent/test_advance.py
git commit -m "feat(career-agent): advance-control picker + screen-signature change detection"
```

---

### Task 6: HumanLoop.collect — gather answers for unknown fields

**Files:**
- Modify: `src/career_agent/integrations/human_loop.py` (add `collect`)
- Test: `tests/career_agent/test_human_loop_collect.py`

**Interfaces:**
- `HumanLoop.collect(fields: list[Field]) -> dict[str,str]` — asks the human for each field's value and returns `{ref: value}`. Delegates to a `collector` (a callable `list[Field] -> dict[str,str]`) injected at construction (`HumanLoop(approver, remote_solve_factory=None, collector=None)`); if no collector, returns `{}` (nothing filled — caller leaves those blank / stops). A `CliCollector` and the Telegram collector implement it; tests inject a fake.

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_human_loop_collect.py
from career_agent.integrations.human_loop import HumanLoop
from career_agent.browser.form_model import Field

class YesApprover:
    def request(self, card): return True

def _f(ref, label): return Field(ref, "text", label, True, [], None, None)

def test_collect_uses_injected_collector():
    fields = [_f("#q", "Why us?")]
    hl = HumanLoop(YesApprover(), collector=lambda fs: {f.ref: "answer:" + f.label for f in fs})
    assert hl.collect(fields) == {"#q": "answer:Why us?"}

def test_collect_without_collector_returns_empty():
    assert HumanLoop(YesApprover()).collect([_f("#q", "Why?")]) == {}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_human_loop_collect.py -v`
Expected: FAIL — `collect`/`collector` missing.

- [ ] **Step 3: Extend `human_loop.py`**

Add `collector=None` to `__init__` (store `self.collector = collector`) and:

```python
    def collect(self, fields) -> dict:
        if self.collector is None or not fields:
            return {}
        return dict(self.collector(fields) or {})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_human_loop_collect.py tests/career_agent/test_human_loop.py -v`
Expected: PASS (existing human_loop tests stay green).

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/integrations/human_loop.py tests/career_agent/test_human_loop_collect.py
git commit -m "feat(career-agent): HumanLoop.collect for unknown-field answers"
```

---

### Task 7: Step engine — the per-screen loop

**Files:**
- Create: `src/career_agent/orchestrator/step_engine.py`
- Test: `tests/career_agent/test_step_engine.py`

**Interfaces:**
- `walk(page, profile, human, deps, max_steps=15, do_submit=False, autonomous=False, on_link=None) -> dict` where `deps` bundles the injectable browser ops (so it's testable without a browser): `deps.snapshot(page)->form`, `deps.gate(page)->str`, `deps.fill(page, decisions)`, `deps.click(page, label)->None`, `deps.url(page)->str`. Returns `{"screens": int, "submitted": bool, "stopped_reason": str, "cards": list}`.
- Per screen: snapshot → gate (interactive escalate → `human.remote_solve`; other escalate gate → stop `reason="gate:<g>"`); `map_screen`; if `needs_human` → `human.collect` then `apply_answers`; `fill`; compute signature; pick advance label; if none and it's the submit step → approval/autonomous submit; click advance; re-snapshot; `changed()` → next screen else stop `reason="stuck"`. Cap at `max_steps`.

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_step_engine.py
from career_agent.browser.form_model import Field
from career_agent.memory.candidate_profile import CandidateProfile
from career_agent.orchestrator.step_engine import walk

class Deps:
    def __init__(self, screens):
        self._screens = screens; self.filled = []; self.clicks = []; self._i = 0
    def snapshot(self, page): return self._screens[min(self._i, len(self._screens)-1)]
    def gate(self, page): return "none"
    def fill(self, page, decisions): self.filled.append(decisions)
    def click(self, page, label): self.clicks.append(label); self._i += 1
    def url(self, page): return f"http://x/step{self._i}"

class Human:
    def approve(self, card): return True
    def remote_solve(self, page, gate, on_link): return True
    def collect(self, fields): return {f.ref: "X" for f in fields}

def _f(ref, label, purpose=None, required=False, kind="text"):
    return Field(ref, kind, label, required, [], None, purpose)

def test_walks_two_screens_then_submits():
    s1 = [_f("#n", "Full name", "full_name"), _f("#c", "Continue", None, kind="button")]
    s2 = [_f("#s", "Submit application", None, kind="button")]
    deps = Deps([s1, s2])
    prof = CandidateProfile(contact={"full_name": "R"})
    out = walk(object(), prof, Human(), deps, do_submit=True, autonomous=True)
    assert out["screens"] >= 2
    assert "Continue" in deps.clicks
    assert out["submitted"] is True

def test_stops_on_unrecoverable_gate():
    class G(Deps):
        def gate(self, page): return "cloudflare_interstitial"
    out = walk(object(), CandidateProfile(), Human(), G([[_f("#a","A")]]))
    assert out["submitted"] is False and out["stopped_reason"].startswith("gate:")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_step_engine.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `step_engine.py`**

```python
# src/career_agent/orchestrator/step_engine.py
"""The multi-page walk: perceive -> gate -> fill -> escalate unknowns -> advance
-> detect change -> repeat, until submit / terminal / cap. Browser ops come via
`deps` so the loop is testable without Playwright."""
from __future__ import annotations

from ..browser.gate_probe import HANDLERS
from ..orchestrator.screen_review import map_screen, apply_answers
from ..orchestrator.advance import screen_signature, changed, pick_advance_label

INTERACTIVE_GATES = {"recaptcha_v2_checkbox", "recaptcha_v2_image",
                     "hcaptcha_checkbox", "hcaptcha_image"}


def walk(page, profile, human, deps, max_steps=15, do_submit=False,
         autonomous=False, on_link=None) -> dict:
    cards, submitted, reason = [], False, "max_steps"
    for _ in range(max_steps):
        form = deps.snapshot(page)
        gate = deps.gate(page)
        if HANDLERS.get(gate, "escalate") == "escalate":
            if gate in INTERACTIVE_GATES:
                if not human.remote_solve(page, gate, on_link or (lambda u: None)):
                    reason = f"gate:{gate}"; break
                gate = deps.gate(page)
            else:
                reason = f"gate:{gate}"; break   # OTP / cloudflare / etc -> stop

        decisions, needs = map_screen(form, profile)
        if needs:
            decisions += apply_answers(needs, human.collect(needs))
        deps.fill(page, decisions)

        before = screen_signature(deps.url(page), form)
        label = pick_advance_label(form, is_last=False)
        submit_label = pick_advance_label(form, is_last=True)
        is_submit = label is None and submit_label is not None

        if is_submit:
            if not do_submit:
                reason = "reached_submit_dry_run"; break
            if autonomous or human.approve("Ready to submit"):
                deps.click(page, submit_label); submitted = True; reason = "submitted"
            else:
                reason = "submit_declined"
            break
        if label is None:
            reason = "no_advance_control"; break

        deps.click(page, label)
        after = screen_signature(deps.url(page), deps.snapshot(page))
        if not changed(before, after):
            reason = "stuck"; break
    return {"screens": max_steps, "submitted": submitted, "stopped_reason": reason, "cards": cards}
```

Note the `screens` count: track it with a local counter incremented each iteration and return that instead of `max_steps` (fix in Step 4 if the test asserts an exact count — the provided test uses `>= 2`, so returning the loop counter is enough; wire a `steps` variable).

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_step_engine.py -v`
Expected: PASS (2 passed). Add a `steps` counter (increment at the top of the loop, `out["screens"]=steps`) so `screens` reflects real iterations.

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/orchestrator/step_engine.py tests/career_agent/test_step_engine.py
git commit -m "feat(career-agent): step engine — multi-page walk (fill/escalate/advance/detect)"
```

---

### Task 8: `apply.py` entrypoint + browser deps wiring

**Files:**
- Create: `src/career_agent/apply.py`
- Create: `src/career_agent/orchestrator/browser_deps.py`
- Test: `tests/career_agent/test_apply_wiring.py`

**Interfaces:**
- `browser_deps.BrowserDeps` — implements `snapshot/gate/fill/click/url` over a real Playwright page (snapshot=`snapshot_form`, gate=`classify_gate`, fill=`apply_decisions`, click=`page.get_by_role("button"|"link", name=label).first.click()`, url=`page.url`).
- `apply.main()` — argparse (`--url` required, `--submit`, `--autonomous`, `--resume-version` default `Rakshit_Singh_draft1`, `--max-steps`); loads `application_profile` + `CandidateProfile`, builds `HumanLoop` (Telegram or CLI, like `run.py`), launches the persistent browser, `page.goto(url)`, settles, calls `walk(...)`, prints the result summary. Wiring only.

- [ ] **Step 1: Write the failing test (wiring is importable + BrowserDeps shape)**

```python
# tests/career_agent/test_apply_wiring.py
def test_browser_deps_has_required_ops():
    from career_agent.orchestrator.browser_deps import BrowserDeps
    for op in ("snapshot", "gate", "fill", "click", "url"):
        assert hasattr(BrowserDeps, op)

def test_apply_main_importable():
    import career_agent.apply as a
    assert hasattr(a, "main")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_apply_wiring.py -v`
Expected: FAIL — modules missing.

- [ ] **Step 3: Write `browser_deps.py`**

```python
# src/career_agent/orchestrator/browser_deps.py
"""Playwright-backed browser ops for the step engine (kept thin; the engine
holds the logic)."""
from __future__ import annotations

from ..browser.perception import snapshot_form
from ..browser.gate_probe import classify_gate
from ..browser.filler import apply_decisions


class BrowserDeps:
    def snapshot(self, page):
        return snapshot_form(page)

    def gate(self, page):
        return classify_gate(page)

    def fill(self, page, decisions):
        apply_decisions(page, decisions)

    def click(self, page, label):
        try:
            page.get_by_role("button", name=label).first.click(timeout=8000)
        except Exception:
            page.get_by_role("link", name=label).first.click(timeout=8000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

    def url(self, page):
        return page.url
```

- [ ] **Step 4: Write `apply.py`**

```python
# src/career_agent/apply.py
"""Entrypoint: walk a full multi-page application from a target URL."""
from __future__ import annotations

import argparse


def main() -> None:
    import sqlite3
    from .config.settings import load_settings
    from .browser.runner import launch, close
    from .orchestrator.browser_deps import BrowserDeps
    from .orchestrator.step_engine import walk
    from .memory.candidate_profile import load_candidate_profile
    from .integrations.approver import CliApprover
    from .integrations.human_loop import HumanLoop
    from job_dashboard.apply.store import get_application_profile

    ap = argparse.ArgumentParser(description="Career agent — multi-page application walk")
    ap.add_argument("--url", required=True)
    ap.add_argument("--db", default="data/jobs.db")
    ap.add_argument("--resume-version", default="Rakshit_Singh_draft1")
    ap.add_argument("--submit", action="store_true")
    ap.add_argument("--autonomous", action="store_true")
    ap.add_argument("--max-steps", type=int, default=15)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    contact = get_application_profile(conn) or {}
    profile = load_candidate_profile(conn, args.resume_version, contact=contact)

    settings = load_settings()
    human = HumanLoop(CliApprover())   # Telegram wiring mirrors run.py when configured
    pw, context, page = launch(settings)
    try:
        page.goto(args.url)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        out = walk(page, profile, human, BrowserDeps(),
                   max_steps=args.max_steps, do_submit=args.submit, autonomous=args.autonomous)
        print(out)
    finally:
        close(pw, context)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests + full suite**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent -q`
Expected: all pass; browser tests SKIP without `RUN_BROWSER_TESTS=1`.

- [ ] **Step 6: Commit**

```bash
git add src/career_agent/apply.py src/career_agent/orchestrator/browser_deps.py tests/career_agent/test_apply_wiring.py
git commit -m "feat(career-agent): apply.py entrypoint + Playwright browser deps for the walk"
```

---

### Task 9: Browser integration — walk a multi-page fixture (skip-marked)

**Files:**
- Create: `tests/career_agent/fixtures/apply_step1.html`, `apply_step2.html`, `apply_done.html`
- Create: `tests/career_agent/test_walk_browser.py`

**Interfaces:** exercises `walk` + `BrowserDeps` over a real 3-page flow linked by a "Continue"/"Submit" button.

- [ ] **Step 1: Create the fixtures**

`apply_step1.html`: a form with `<label>Full name</label><input id=name>` and `<a href="apply_step2.html">Continue</a>` styled as a button (role=link named "Continue").
`apply_step2.html`: `<label>Employer</label><input id=emp>` + `<a href="apply_done.html" role="button">Submit application</a>`.
`apply_done.html`: `<h1>Application submitted</h1>` (no controls).

```html
<!-- tests/career_agent/fixtures/apply_step1.html -->
<!doctype html><body><form>
<label for=name>Full name</label><input id=name name=name>
</form><a href="apply_step2.html">Continue</a></body>
```
```html
<!-- tests/career_agent/fixtures/apply_step2.html -->
<!doctype html><body><form>
<label for=emp>Employer</label><input id=emp name=emp>
</form><button onclick="location.href='apply_done.html'">Submit application</button></body>
```
```html
<!-- tests/career_agent/fixtures/apply_done.html -->
<!doctype html><body><h1>Application submitted</h1></body>
```

- [ ] **Step 2: Write the skip-marked test**

```python
# tests/career_agent/test_walk_browser.py
import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1",
                                reason="set RUN_BROWSER_TESTS=1 to run")

def _url(name):
    return (Path(__file__).parent / "fixtures" / name).resolve().as_uri()

def test_walks_fixture_flow_and_submits():
    from playwright.sync_api import sync_playwright
    from career_agent.orchestrator.browser_deps import BrowserDeps
    from career_agent.orchestrator.step_engine import walk
    from career_agent.memory.candidate_profile import CandidateProfile, Experience

    prof = CandidateProfile(contact={"full_name": "Rakshit"},
                            experiences=[Experience("Tata AIG", "Data Scientist")])
    class Human:
        def approve(self, card): return True
        def remote_solve(self, p, g, o): return True
        def collect(self, fields): return {}
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(); page.goto(_url("apply_step1.html"))
        out = walk(page, prof, Human(), BrowserDeps(), do_submit=True, autonomous=True)
        landed = page.url
        b.close()
    assert out["submitted"] is True
    assert landed.endswith("apply_done.html")
```

- [ ] **Step 3: Run it (opt-in) + full suite**

Run: `PYTHONPATH=src RUN_BROWSER_TESTS=1 <venv>/bin/python -m pytest tests/career_agent/test_walk_browser.py -v`
Expected: PASS — the walk fills name on step1, clicks Continue, fills employer on step2, clicks Submit, lands on the done page. Then `PYTHONPATH=src python3 -m pytest tests/career_agent -q` — this test SKIPS, rest green.

- [ ] **Step 4: Commit**

```bash
git add tests/career_agent/fixtures/apply_step1.html tests/career_agent/fixtures/apply_step2.html tests/career_agent/fixtures/apply_done.html tests/career_agent/test_walk_browser.py
git commit -m "test(career-agent): browser walk over a 3-page apply fixture"
```

---

### Task 10: Live extraction sanity — CandidateProfile from the real résumé

**Files:** none (manual/verification task; optionally a one-off script under the scratchpad).

- [ ] **Step 1: Verify extraction against the real saved résumé**

Run a one-off (not committed) to confirm the extraction produces sane experiences/skills from `Rakshit_Singh_draft1`:
```bash
PYTHONPATH=src python3 -c "
import sqlite3; from career_agent.memory.candidate_profile import load_candidate_profile
p = load_candidate_profile(sqlite3.connect('data/jobs.db'))
print('experiences:', [(e.company, e.title, e.start, e.end) for e in p.experiences])
print('skills:', p.skills[:15])"
```
Expected: Tata AIG / OYO experiences with titles+dates, a real skills list. If role titles/dates come out empty, that's the signal to wire the qwen3:14b `split` callback for the fuzzy role-header titles (bounded extraction) — implement `job_dashboard.resume.resume_llm`-style `make_ollama_llm` call as the `split` and pass it into `load_candidate_profile`.

- [ ] **Step 2: Record the outcome**

Note in the ledger whether rule-based extraction sufficed or the LLM `split` was needed, and commit any `split` wiring added.

---

## Self-Review (completed by plan author)

- **Spec coverage:** step-loop (Task 7), résumé→profile (Task 1), richer purposes + resolver + screen mapper (Tasks 2–4), advance/step-change (Task 5), human escalation collect (Task 6), apply entrypoint + browser deps (Task 8), browser walk (Task 9), live extraction check (Task 10). Deferred B/C/D/E are honored: OTP/other gates stop with `reason="gate:*"`; novel questions escalate via `collect`; submit approval-gated unless `autonomous`. ✔
- **No-evasion / attestations:** step engine escalates non-interactive gates and never bypasses; `map_screen` emits attestation decisions that are never valued (Phase-1 filler leaves them). ✔
- **Placeholder scan:** every code/test step has real code; the two "adjust if…" notes point at concrete fixes, not TODOs. ✔
- **Type consistency:** `FillDecision` fields match Phase-1; `map_screen` returns `(decisions, needs_human)` used by Task 7; `resolve(purpose, profile, index)` signature matches Task 4's use; `walk(page, profile, human, deps, …)` matches Task 8's call and Task 9's test. ✔
