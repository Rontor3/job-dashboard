# Resume Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Checkbox steps. Dispatch prompts in caveman style (project memory).

**Goal:** Per-job tailored, ATS-safe resumes from the candidate's real CV — modular blocks the user picks, truthful keyword-mapping (never fabricate), LaTeX render, ATS check on the final PDF, saved against each job, driven from a dashboard panel.

**Architecture:** New `src/job_dashboard/resume/` package: `segments.py` (block library loader), `keyword_map.py` (truthful rephrasing proposals), `render.py` (blocks→LaTeX→PDF via injectable renderer), `ats.py` (pdftotext parse checks), `fit.py` (keyword-aware overflow cutting), `engine.py` (orchestrates suggest→generate). `db.py` gains a `resumes` table. API adds resume endpoints; frontend adds a Tailor-resume panel. LaTeX reuses the vendored ai-job-search `cv/` template.

**Tech Stack:** Python 3.11+, lualatex (`/Library/TeX/texbin`), pdftotext (installed), pytest (renderer injected/mocked — LaTeX not required in CI), React (existing frontend).

## Global Constraints

- **Segment integrity:** blocks contain only content already true in the source CV (`cv/main_example.tex` + `01-candidate-profile.md`). No task may fabricate experience.
- **Keyword-map policy = "truthful map + flag transferable"** (spec §Adaptive block phrasing): propose rephrasings of REAL blocks tagged `exact-synonym`/`equivalent`/`transferable — verify`; NEVER write a tool/skill the candidate didn't use; true gaps stay flagged, never faked; every rephrasing is a user-approved option.
- **ATS check runs LAST**, on the final cut PDF (the exact artifact submitted).
- **Fit-loop is keyword-aware:** JD-keyword-rich lines survive over generic ones; `log()` what was cut (no silent truncation).
- Renderer is injectable; tests never require lualatex. `render.py` resolves lualatex via `/Library/TeX/texbin` + `shutil.which`; a missing binary raises a clear "install MacTeX" error, never a silent failure.
- Generated PDFs under `documents/generated/` (gitignored — `documents/` already is).
- db.py is the only SQL. Existing 79 tests stay green.

---

## File Structure

```
src/job_dashboard/
  db.py                       # + resumes table & queries
  resume/
    __init__.py
    segments.py               # load_segments() -> list[Segment]; Segment dataclass
    keyword_map.py            # propose_rephrasings(blocks, jd, deep_rank) -> list[Rephrasing]
    render.py                 # compose(blocks)->tex ; render_pdf(tex, out) (injectable lualatex)
    ats.py                    # ats_check(pdf_path, jd) -> AtsReport
    fit.py                    # fit_to_page(lines, jd_keywords, overflow_fn) -> (kept, cut)
    engine.py                 # suggest_blocks(...), generate_resume(...)
  resume_segments/            # the block library (LaTeX snippets + manifest)
    segments.yaml
    *.tex
  api/app.py                  # + resume endpoints
frontend/src/components/
    ResumePanel.jsx           # Tailor-resume panel
tests/
    test_resume_segments.py test_resume_keyword_map.py test_resume_render.py
    test_resume_ats.py test_resume_fit.py test_resume_engine.py
    test_resume_api.py
    (frontend) resume_panel.test.jsx
```

---

### Task 1: Segment library — decompose the real CV into blocks + loader

**Files:** Create `src/job_dashboard/resume/__init__.py`, `src/job_dashboard/resume/segments.py`, `src/job_dashboard/resume_segments/segments.yaml` + `*.tex` blocks; Test `tests/test_resume_segments.py`.

**Interfaces:** `Segment(id, kind, title, tags: list[str], tex_path, text)`; `load_segments(root=SEGMENTS_DIR) -> list[Segment]`; `SEGMENTS_DIR = repo/src/job_dashboard/resume_segments`.

**Content step (human-content, integrity-critical):** read `.claude/skills/ai-job-search/cv/main_example.tex` + `01-candidate-profile.md`; split into blocks — header, summary variants (2–3), skills groups, one per project (RAG, LoRA, fraud pipeline, RoamMate, resume-matcher), experience-framings, education. Each `.tex` snippet holds ONLY text already in the source CV. `segments.yaml` lists each: `{id, kind, title, tags:[keywords], tex: filename}`.

- [ ] Step 1 — failing test:
```python
# tests/test_resume_segments.py
from job_dashboard.resume.segments import load_segments, Segment

def test_loads_blocks_with_manifest_and_tex(tmp_path):
    (tmp_path / "a.tex").write_text(r"\section{Skills} Python, ML")
    (tmp_path / "segments.yaml").write_text(
        "segments:\n  - id: skills-core\n    kind: skills\n    title: Core Skills\n"
        "    tags: [python, ml]\n    tex: a.tex\n")
    segs = load_segments(tmp_path)
    assert len(segs) == 1
    s = segs[0]
    assert isinstance(s, Segment) and s.id == "skills-core"
    assert s.tags == ["python", "ml"]
    assert "Python, ML" in s.text

def test_missing_tex_file_raises_clear_error(tmp_path):
    (tmp_path / "segments.yaml").write_text(
        "segments:\n  - id: x\n    kind: skills\n    title: X\n    tags: []\n    tex: nope.tex\n")
    import pytest
    with pytest.raises(FileNotFoundError, match="nope.tex"):
        load_segments(tmp_path)
```
- [ ] Step 2 — run → FAIL (module missing).
- [ ] Step 3 — implement `segments.py` (dataclass + yaml load + read each tex; `pip3 install pyyaml` if absent, add to requirements). Then author the real `resume_segments/` blocks + manifest from the CV (integrity rule — no invented content).
- [ ] Step 4 — add a test asserting the REAL library loads and every segment's text is non-empty: `test_real_segment_library_loads` (points at the default SEGMENTS_DIR).
- [ ] Step 5 — `python3 -m pytest tests/test_resume_segments.py` → PASS; full suite green.
- [ ] Step 6 — commit `feat: resume segment library — decompose CV into reusable blocks + loader`.

---

### Task 2: DB — resumes table + queries

**Files:** Modify `src/job_dashboard/db.py`; Test `tests/test_resume_db.py`.

**Interfaces:** `save_resume(conn, job_id, pdf_path, blocks_used:list, ats_score, ats_report:dict) -> int`; `resumes_for_job(conn, job_id) -> list[dict]`; `get_resume(conn, resume_id) -> dict|None`. Idempotent `_ensure_resumes_table` mirroring `_ensure_status_column`.

- [ ] Step 1 — failing tests: save one, read back via `resumes_for_job` (blocks_used/ats_report round-trip JSON), `get_resume` returns it, unknown id → None. (Follow tests/test_db_dashboard.py style + `_seed` helper.)
- [ ] Step 2 — FAIL. Step 3 — implement: `resumes` table `(id, job_id, pdf_path, blocks_used TEXT, ats_score REAL, ats_report TEXT, created_at TEXT)`; the three functions (json.dumps/loads for blocks_used/ats_report); wire `_ensure_resumes_table` into `init_db`.
- [ ] Step 4 — PASS; full suite green. Step 5 — commit `feat: resumes table + queries in db.py`.

---

### Task 3: LaTeX render — compose blocks → PDF (injectable renderer)

**Files:** Create `src/job_dashboard/resume/render.py`; Test `tests/test_resume_render.py`.

**Interfaces:** `compose(blocks: list[Segment], template=DEFAULT_TEMPLATE) -> str` (assembled .tex); `render_pdf(tex: str, out_dir, runner=None) -> Path` where `runner(tex_path, out_dir)->pdf_path` defaults to the real lualatex runner. `lualatex_path()` resolves `/Library/TeX/texbin/lualatex` or `shutil.which("lualatex")`, else raises `RuntimeError("lualatex not found — install MacTeX")`.

- [ ] Step 1 — failing tests (NO real LaTeX): `compose` splices block `text` into the template between markers; `render_pdf` with an injected fake runner (writes a dummy `out.pdf`, returns its path) returns that path and wrote the composed .tex; `lualatex_path` raises the clear error when `runner`/binary absent (monkeypatch `shutil.which -> None` and the texbin path check).
```python
def test_render_pdf_uses_injected_runner(tmp_path):
    from job_dashboard.resume.render import render_pdf
    def fake_runner(tex_path, out_dir):
        p = out_dir / "out.pdf"; p.write_bytes(b"%PDF-1.5 fake"); return p
    pdf = render_pdf(r"\documentclass{article}\begin{document}x\end{document}",
                     tmp_path, runner=fake_runner)
    assert pdf.read_bytes().startswith(b"%PDF")
```
- [ ] Step 2 — FAIL. Step 3 — implement compose + render_pdf + the real lualatex runner (subprocess `lualatex -interaction=nonstopmode -output-directory`, 2 passes, cwd handling, raises on nonzero with the compile log tail).
- [ ] Step 4 — PASS. Step 5 — **live smoke test, skipped without lualatex**:
```python
import shutil, pytest
@pytest.mark.skipif(not shutil.which("lualatex") and not __import__("pathlib").Path("/Library/TeX/texbin/lualatex").exists(), reason="no lualatex")
def test_real_lualatex_smoke(tmp_path):
    from job_dashboard.resume.render import render_pdf
    pdf = render_pdf(r"\documentclass{article}\begin{document}Hello, ATS.\end{document}", tmp_path)
    assert pdf.exists() and pdf.read_bytes().startswith(b"%PDF")
```
Run it live (toolchain is installed) — confirm real PDF.
- [ ] Step 6 — full suite green; commit `feat: LaTeX render — compose blocks to PDF, injectable lualatex runner`.

---

### Task 4: ATS check — parse the final PDF as a machine would

**Files:** Create `src/job_dashboard/resume/ats.py`; Test `tests/test_resume_ats.py`.

**Interfaces:** `ats_check(pdf_path, jd_text, extract=None) -> AtsReport` where `extract(pdf_path)->str` defaults to real `pdftotext`; `AtsReport(ats_score:int, contact_ok:bool, reading_order_ok:bool, keyword_coverage:float, missing_keywords:list[str], warnings:list[str])`.

Checks on the extracted text: contact (email regex + phone present), keyword coverage = fraction of JD's salient keywords present (simple tokenized set-overlap for v1; the JD keywords can come from the deep-rank later — v1 tokenizes the JD), reading-order heuristic (section headers appear in a sane sequence), garbled-glyph warning (high ratio of non-ascii/replacement chars). `ats_score` = weighted blend (contact 30, coverage 50, reading-order 20).

- [ ] Step 1 — failing tests with an injected `extract` returning canned text: a clean resume text (email+phone+keywords) → high score, contact_ok, coverage>0.5; a parse-hostile text (no email, garbled) → low score, contact_ok False, warning present; missing_keywords lists JD terms absent from the resume text.
- [ ] Step 2 — FAIL. Step 3 — implement (pure text logic + default `pdftotext` subprocess extract). Step 4 — PASS.
- [ ] Step 5 — live test (pdftotext IS installed, not skipped): render the smoke doc via Task 3's real runner, run real `ats_check` on it, assert contact/keyword logic on real extracted text.
- [ ] Step 6 — commit `feat: ATS check — pdftotext parse, contact/coverage/reading-order scoring`.

---

### Task 5: Fit-loop — keyword-aware overflow cutting

**Files:** Create `src/job_dashboard/resume/fit.py`; Test `tests/test_resume_fit.py`.

**Interfaces:** `rank_lines(lines: list[str], jd_keywords: set[str]) -> list[(score, line)]` (score = JD-keyword hits + uniqueness); `fit_to_page(lines, jd_keywords, overflows) -> FitResult(kept, cut)` where `overflows(candidate_lines)->bool` is injected (in prod = render+measure page count; in tests = a fake). Cuts lowest-ranked line, re-checks, repeats until `not overflows`.

- [ ] Step 1 — failing test: given lines where a keyword-rich line and generic lines, and a fake `overflows` that returns True until len<=N, assert the keyword-rich line is in `kept` and the lowest-value generic lines are in `cut`, and `cut` is logged/returned.
- [ ] Step 2 — FAIL. Step 3 — implement. Step 4 — PASS; commit `feat: keyword-aware fit-loop for one-page overflow cutting`.

---

### Task 6: Engine — suggest blocks + truthful keyword-mapping + generate

**Files:** Create `src/job_dashboard/resume/keyword_map.py`, `src/job_dashboard/resume/engine.py`; Test `tests/test_resume_keyword_map.py`, `tests/test_resume_engine.py`.

**Interfaces:**
- `propose_rephrasings(segments, jd_text, deep_rank, llm=None) -> list[Rephrasing]` where `Rephrasing(block_id, original_text, proposed_text, jd_keyword, confidence in {exact-synonym,equivalent,transferable}, needs_interview_prep:bool)`. `llm` injected; the prompt HARD-FORBIDS naming a tool/skill not in the block's own text; a JD keyword with no truthful mapping is returned as a gap (`GapKeyword(jd_keyword)`), never a rephrasing. Deterministic tests use a fake llm.
- `suggest_blocks(segments, jd_text, deep_rank, llm=None) -> {block_ids, rationale, rephrasings, gaps}`.
- `generate_resume(conn, job_id, block_ids, accepted_rephrasings, *, segments, jd_text, render_pdf, ats_check, fit_to_page, out_dir) -> dict` — applies accepted rephrasings to block text, composes, fit-loops, renders final PDF, ATS-checks the final PDF, saves a resumes row, returns `{resume_id, pdf_path, ats_report, blocks_used, cut_lines, interview_prep}`.

- [ ] Step 1 — failing tests:
  - keyword_map: fake llm proposes a mapping that (a) reuses only block text → accepted with correct confidence tag; (b) a fabricated-tool proposal (names "Kafka" absent from block) → `propose_rephrasings` MUST reject/drop it (integrity guard) and emit the keyword as a `GapKeyword`. Assert no Rephrasing contains a token absent from its block's source text.
  - engine: `generate_resume` with injected fakes (fake render_pdf → dummy pdf, fake ats_check → canned report, fake fit_to_page → identity) writes a resumes row and returns the report + interview_prep listing accepted `transferable` claims.
- [ ] Step 2 — FAIL. Step 3 — implement keyword_map (with the integrity guard that drops any proposed_text containing a non-source token for tool-like keywords) + engine orchestration. Step 4 — PASS.
- [ ] Step 5 — full suite green; commit `feat: resume engine — block suggestion, truthful keyword-mapping, generate orchestration`.

---

### Task 7: API endpoints

**Files:** Modify `src/job_dashboard/api/app.py`; Test `tests/test_resume_api.py`.

**Interfaces (mirror existing endpoint style + TestClient):**
- `GET /api/resume/segments` → block manifest.
- `POST /api/jobs/{id}/resume/suggest` → `{block_ids, rationale, rephrasings, gaps}` (uses the job's stored deep-rank + description).
- `POST /api/jobs/{id}/resume/generate` `{block_ids, accepted_rephrasings}` → runs engine, returns `{resume_id, pdf_url, ats_report, blocks_used, cut_lines, interview_prep}`; 503 with actionable message if lualatex missing.
- `GET /api/jobs/{id}/resumes` → prior generations.
- `GET /api/resumes/{id}/pdf` → serves the PDF (FileResponse).

`create_app` gains injectable `resume_engine=None` (default wires the real modules) so tests inject a fake engine — no LaTeX/LLM in API tests.

- [ ] Steps: failing TestClient tests (suggest/generate/list/pdf/segments, 404s, 503-when-no-lualatex via a fake engine that raises the missing-binary error) → implement → PASS → commit `feat: resume API endpoints (suggest/generate/list/pdf/segments)`.

---

### Task 8: Dashboard "Tailor resume" panel

**Files:** Create `frontend/src/components/ResumePanel.jsx`; Modify `frontend/src/components/JobDetail.jsx`, `frontend/src/api.js`; Test `frontend/src/__tests__/resume_panel.test.jsx`.

**Interfaces:** `api.js` adds `fetchSegments`, `suggestResume(id)`, `generateResume(id, blockIds, acceptedRephrasings)`, `fetchResumes(id)`. `<ResumePanel jobId />` in the detail panel: "Tailor resume" button → suggest → block toggles (suggested pre-checked) + per-rephrasing inline "could read as…" diff with confidence tag + accept toggle + amber gap chips → Generate → inline PDF link + ATS score + missing-keyword chips + interview-prep list. Teal v2 tokens; reduced-motion respected.

- [ ] Steps: failing Vitest tests (renders suggested blocks from fetch mock; toggling + generate calls generateResume with chosen block ids + accepted rephrasings; gap chips render; ATS score + interview-prep render from the generate response) → implement → PASS → `npm run build` → commit `feat: Tailor-resume dashboard panel with keyword-map diffs and ATS score`.

---

## After the plan

- Live end-to-end on one real job (toolchain installed): suggest → pick blocks → generate → confirm real tailored PDF + ATS score + interview-prep, in the browser.
- Whole-branch review + finishing-a-development-branch.
- THEN: Cover Letters (subsystem 4), then the Application Agent (company-site auto-apply, review→submit).

## Not covered (spec non-goals)

Cover letters; auto-apply; multi-page/multi-template/DOCX; editing block content in the UI.
