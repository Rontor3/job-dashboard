# Résumé Block Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A block editor for Skills/Experience/Projects — reorder, regenerate (grounded), edit, add, delete — driving résumé generation.

**Architecture:** Small backend additions on the existing engine: `custom_block.py` (text→LaTeX, escaped), `regenerate_block` (grounded alternatives), a `layout` path in `generate_resume`, two API endpoints; then the ResumePanel editor UI (prototype v4). Reuses compose/lualatex/fit/ATS untouched.

**Tech Stack:** Python 3.11 + pytest; React + Vite + Vitest; lualatex (guarded live test).

## Global Constraints

- Python 3.11, pytest; React/Vite/Vitest; files under 500 lines.
- **Grounding: never invent numbers** — an unsupported metric becomes the literal `[add number]`.
- **Original content never destroyed** — it is always `variants[0]`.
- **All user text LaTeX-escaped** before rendering.
- Backward-compat: the old `block_ids` generate path keeps working.
- Reuse: `compose`/lualatex/fit/ATS pipeline, `suggest_blocks`, segment loading, cover-letter/screening grounding style.

---

### Task 1: `custom_block.py` — text → escaped LaTeX

**Files:** Create `src/job_dashboard/resume/custom_block.py`; Test `tests/test_custom_block.py`

**Interfaces:** Produces `escape_tex(s)->str`; `block_to_tex(kind, title, bullets)->str` (LaTeX `\item` lines matching segments; never raises).

- [ ] **Step 1: failing test** — `tests/test_custom_block.py`:

```python
from job_dashboard.resume.custom_block import escape_tex, block_to_tex


def test_escape_tex_specials():
    assert escape_tex("a & b 50% $x #1 _y {z}") == r"a \& b 50\% \$x \#1 \_y \{z\}"


def test_experience_block_is_items_escaped():
    tex = block_to_tex("experience", "DS at Acme", ["Cut cost 20%", "Shipped ML"])
    assert r"\item Cut cost 20\%" in tex
    assert r"\item Shipped ML" in tex


def test_project_and_skills_lead_with_bold_title():
    proj = block_to_tex("project", "RoamMate", ["AI travel app"])
    assert r"\item \textbf{RoamMate}" in proj
    skills = block_to_tex("skills", "GenAI / LLM", ["RAG", "LoRA"])
    assert r"\textbf{GenAI / LLM}" in skills and "RAG" in skills


def test_never_raises_on_odd_input():
    assert isinstance(block_to_tex("experience", None, [None, "", "ok"]), str)
    assert block_to_tex("skills", "x", []) == "" or "\\item" not in block_to_tex("skills", "x", [])
```

- [ ] **Step 2:** run `pytest tests/test_custom_block.py -v` → FAIL.

- [ ] **Step 3:** implement `custom_block.py`:

```python
"""User block text -> LaTeX \\item lines matching resume_segments/*.tex.
Every user string is escaped so a stray % / & / $ can't break lualatex.
Never raises."""
from __future__ import annotations

_ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}"}


def escape_tex(s) -> str:
    out = []
    for ch in str(s or ""):
        out.append(_ESC.get(ch, ch))
    return "".join(out)


def _clean_bullets(bullets):
    return [str(b).strip() for b in (bullets or []) if b and str(b).strip()]


def block_to_tex(kind, title, bullets) -> str:
    """Return \\item lines for a block. experience: one item per bullet.
    project/skills: lead the first item with \\textbf{title}."""
    items = _clean_bullets(bullets)
    if not items:
        return ""
    k = (kind or "").lower()
    lead = escape_tex(title) if title else ""
    lines = []
    if k in ("project", "skills") and lead:
        first = escape_tex(items[0])
        if k == "skills":
            body = ", ".join(escape_tex(b) for b in items)
            return rf"\item \textbf{{{lead}}}: {body}"
        lines.append(rf"\item \textbf{{{lead}}}: {first}")
        rest = items[1:]
    else:
        rest = items
    for b in rest:
        lines.append(rf"\item {escape_tex(b)}")
    return "\n".join(lines)
```

- [ ] **Step 4:** run `pytest tests/test_custom_block.py -v` → PASS.
- [ ] **Step 5:** commit `feat(resume): custom_block text->escaped LaTeX`.

---

### Task 2: `regenerate_block` — grounded alternatives

**Files:** Modify `src/job_dashboard/resume/resume_llm.py`; Test `tests/test_regenerate_block.py`

**Interfaces:** `regenerate_block(kind, title, bullets, jd_text, profile_text, llm=None, n=2) -> list[list[str]]` — up to n alt bullet-sets; unsupported numbers → `[add number]`; never raises → `[]` on failure.

- [ ] **Step 1: failing test** — `tests/test_regenerate_block.py`:

```python
from job_dashboard.resume.resume_llm import regenerate_block


def test_returns_alternatives_from_fake_llm():
    fake = lambda p: "1. Built **fraud** ML cutting cost 20%\n2. Shipped real-time scoring"
    alts = regenerate_block("experience", "DS", ["Built fraud models", "cut cost 20%"],
                            "Need ML engineer", "3 years fraud ML, cut cost 20%", llm=fake, n=2)
    assert len(alts) >= 1 and all(isinstance(a, list) for a in alts)


def test_unsupported_number_becomes_placeholder():
    fake = lambda p: "1. Boosted revenue by 87% overnight"
    alts = regenerate_block("experience", "DS", ["Improved revenue"],
                            "jd", "worked on revenue models", llm=fake, n=1)
    flat = " ".join(alts[0]) if alts else ""
    assert "87%" not in flat
    assert "[add number]" in flat


def test_llm_failure_returns_empty_never_raises():
    def boom(p): raise RuntimeError("ollama down")
    assert regenerate_block("experience", "DS", ["x"], "jd", "prof", llm=boom) == []
```

- [ ] **Step 2:** run → FAIL.

- [ ] **Step 3:** implement `regenerate_block` in `resume_llm.py`. Default `llm` = the generic prompt→text seam `from job_dashboard.letter.draft import make_default_llm` (the same one screening/cover-letter use — NOT `make_ollama_llm`, which is keyword-specialized). Prompt asks for `n` alternatives, each 1–3 impact bullets, **bold** key terms, only numbers present in the source; parse numbered lines into bullet-sets. Then a grounding pass: for each bullet, any number token (`\b\d[\d.,]*%?\b`, currency) not found in `bullets`+`profile_text` is replaced with `[add number]`. Wrap the whole body in try/except → `[]`.

```python
import re

def _supported_numbers(text):
    return set(re.findall(r"\d[\d.,]*", text or ""))

def _ground_bullet(b, allowed):
    def repl(m):
        return m.group(0) if m.group(0).replace(",", "") in allowed or m.group(0) in allowed else "[add number]"
    # replace standalone numbers (incl % / currency-adjacent) not in allowed
    return re.sub(r"\d[\d.,]*", repl, b)

def regenerate_block(kind, title, bullets, jd_text, profile_text, llm=None, n=2):
    try:
        if llm is None:
            from job_dashboard.letter.draft import make_default_llm
            llm = make_default_llm()
        prompt = (
            f"Rewrite this resume block as {n} punchy alternatives tailored to the JD. "
            "Each alternative: 1-3 bullets, **bold** key terms, keep only numbers that "
            "already appear in the source; do NOT invent metrics.\n\n"
            f"BLOCK ({kind}) {title}:\n" + "\n".join(f"- {b}" for b in bullets) +
            f"\n\nJD:\n{(jd_text or '')[:1500]}\n\nCANDIDATE FACTS:\n{(profile_text or '')[:1200]}\n\n"
            "Reply as:\n1. <bullet> / <bullet>\n2. <bullet> / <bullet>")
        out = llm(prompt)
        allowed = _supported_numbers(" ".join(bullets or []) + " " + (profile_text or ""))
        alts = []
        for line in re.split(r"\n(?=\d+[.)])", out if isinstance(out, str) else ""):
            line = re.sub(r"^\s*\d+[.)]\s*", "", line).strip()
            if not line:
                continue
            parts = [_ground_bullet(p.strip(), allowed) for p in re.split(r"\s*/\s*|\n", line) if p.strip()]
            if parts:
                alts.append(parts[:3])
            if len(alts) >= n:
                break
        return alts
    except Exception:
        return []
```

(`make_default_llm()` returns an `llm(prompt)->str` callable; confirmed the seam used by `apply/screening.py` and the cover-letter draft.)

- [ ] **Step 4:** run → PASS. **Step 5:** commit `feat(resume): grounded per-block regenerate`.

---

### Task 3: `generate_resume` — ordered `layout` path

**Files:** Modify `src/job_dashboard/resume/engine.py`; Test `tests/test_generate_layout.py`

**Interfaces:** `generate_resume(..., layout=None, ...)` — when `layout` (ordered list of `{"segment_id"}` or `{"kind","title","bullets"}`) is given, it drives composition (fixed header/summary/education prepended); else the `block_ids` path is unchanged.

- [ ] **Step 1: failing test** (fake render/ats): assert a layout `[{"segment_id": "<real skills id>"}, {"kind":"project","title":"P","bullets":["did x"]}]` composes both in order (the custom block's `\item \textbf{P}` appears in the tex passed to the fake renderer). Use the existing `test_resume_*` fixtures/fakes as a model.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement: add `layout=None` kwarg. When set, build the ordered block list: map `{"segment_id"}`→`seg_by_id[id]`; map custom→`Segment(id=f"custom-{i}", kind=kind, title=title, tags=[], tex_path=None, text=block_to_tex(kind,title,bullets))`; prepend the fixed segments (`header-contact`, `summary-main`, any `education-*`) if present in `segments`; then run the SAME (b)…(g) pipeline (rephrasings only apply to real segments). Keep `block_ids` path as the `else`.
- [ ] **Step 4:** run → PASS (+ existing `test_resume*` green). **Step 5:** commit `feat(resume): generate_resume accepts ordered layout`.

---

### Task 4: API — regenerate-block + layout generate

**Files:** Modify `src/job_dashboard/api/resume_routes.py`; Test `tests/test_resume_api_editor.py`

**Interfaces:** `POST /api/jobs/{id}/resume/regenerate-block` `{kind,title,bullets}`→`{alternatives}`; `POST …/resume/generate` accepts optional `layout`.

- [ ] Steps 1–2: test both endpoints (fake llm / injected engine): regenerate-block returns alternatives; generate with `layout` calls the engine layout path. → FAIL.
- [ ] Step 3: add the regenerate-block route (calls `regenerate_block` with `compose_profile_text().text` + job JD); extend the generate route's request model with optional `layout` and pass it through. → PASS.
- [ ] Steps 4–5: run + `pytest tests/test_resume_api*.py -q`; commit `feat(api): résumé regenerate-block + layout generate`.

---

### Task 5: Frontend — ResumePanel block editor

**Files:** Modify `frontend/src/components/ResumePanel.jsx` (+ `frontend/src/api.js`); Test `frontend/src/__tests__/resume_panel.test.jsx` (extend)

**Interfaces:** Consumes `suggest`+`segments`, new `regenerateBlock(id,{kind,title,bullets})`, `generateResume(id,{layout})`.

- [ ] **Step 1:** read the current `ResumePanel.jsx` and the prototype behavior in the spec. Add `api.js`: `regenerateBlock = (id,body)=>POST /resume/regenerate-block`; extend `generateResume` to send `{layout}`.
- [ ] **Step 2:** replace the checkbox block list (stage "suggested") with the editor: build editor blocks from `segments` filtered to kinds `skills`/`experience`/`project` (Original = the segment's bullets; suggested subset pre-included). Implement per the prototype: drag-reorder within kind, **regenerate** (calls the endpoint, shows alternatives, Original kept), **edit** (inline title+bullets → "Your edit"), **add** (blank custom block), **delete**, live preview. Mirror the prototype's markup/handlers; reuse existing panel styling/tokens.
- [ ] **Step 3:** "Generate" builds the ordered `layout` (unchanged segment block → `{segment_id}`; edited/added/alternative-picked → `{kind,title,bullets}`) and posts it; the existing generated-PDF + ATS report display is reused.
- [ ] **Step 4:** extend `resume_panel.test.jsx` (mock `global.fetch` for suggest/segments/regenerate-block/generate): editor renders blocks; regenerate shows alternatives; edit updates preview; generate posts a `layout`. Run `npm --prefix frontend test -- resume_panel` and `npm --prefix frontend run build`.
- [ ] **Step 5:** commit `feat(ui): résumé block editor (drag/regenerate/edit/add/delete)`.

---

### Task 6: Live e2e + finish

- [ ] **Step 1:** full suites — `pytest -q` and `npm --prefix frontend test`.
- [ ] **Step 2:** live e2e (manual, with the candidate): open a Strong-Fit job → editor shows Skills/Experience/Projects blocks → reorder → regenerate a block (grounded alternatives, original kept) → edit one → add a project → **Generate** → PDF renders with the new order/content and a real ATS report.
- [ ] **Step 3:** commit any runbook note; final whole-branch review.

## Self-Review

- **Spec coverage:** LaTeX-safe custom blocks (T1); grounded regenerate (T2); ordered layout generate (T3); API (T4); editor UI drag/regenerate/edit/add/delete (T5); e2e (T6).
- **Placeholders:** backend tasks carry real code; T5 is detailed steps against the prototype + real file (justified — it mirrors unseen component markup).
- **Type consistency:** `block_to_tex(kind,title,bullets)` used by T3; `regenerate_block(...)->list[list[str]]` used by T4; `layout` shape identical across T3/T4/T5.
- **Risk pinned:** T1 includes escaping + a guarded live-lualatex render so a custom block provably compiles; grounding (`[add number]`) tested in T2.
