# Resume Engine — Design

## Purpose

Generate a **tailored, ATS-safe resume per job** from the candidate's real CV, reviewed
and rendered inside the dashboard. Subsystem 3 of the master design
(`2026-07-12-job-dashboard-design.md` §3). Produces the artifact the later Application
Agent presents for the user's approve-then-submit flow.

Decisions fixed (user-confirmed 2026-07-24): **modular segments the user picks** (no
LLM rewrite — blocks only ever contain content already in the real CV); **dashboard
surface** (a "Tailor resume" panel on each job's detail); **ATS check runs LAST, on the
final cut PDF** (it must score the exact file that gets submitted).

## Hard dependency (execution gate)

LaTeX rendering needs **MacTeX** (`lualatex`) — not installed yet
(`brew install --cask mactex-no-gui`). `pdftotext` (poppler, the ATS-check half) is
already installed. **Design/build/tests do NOT need MacTeX** — the renderer is injected
and mocked; only real generation on the user's machine needs it. This spec + its plan
can be written and (mostly) built before MacTeX lands; live end-to-end generation waits
on the install.

## Segment library (source of truth)

The candidate's real CV — `.claude/skills/ai-job-search/cv/main_example.tex` +
`01-candidate-profile.md` (both already populated by /setup) — is decomposed **once**
into reusable blocks:
- header/contact, 2–3 summary variants, skill groups, one block per project (RAG, LoRA,
  fraud pipeline, RoamMate, resume-matcher…), one per experience-framing, education.
- Stored as LaTeX snippet files + a manifest: `resume/segments/*.tex` + `segments.yaml`
  (each entry: id, kind, title, tags/keywords, source-of-truth line refs).
- **Integrity rule:** blocks contain only content already in the real CV. No block may
  introduce experience/skills the candidate doesn't have. A later regeneration never
  fabricates — it only re-selects/reorders existing blocks.

## Per-job block suggestion

For a job, an LLM proposes which blocks to include + their order, using that job's
**already-computed `strengths`/`gaps`/keywords from the deep-rank** (match_scores) plus
the JD text. Output: `{suggested_block_ids: [...], emphasis: {...}, rationale}`. The user
sees this as pre-checked toggles — they add/remove blocks before generating.

## Generation pipeline (ordering is binding)

1. **Compose** the chosen blocks into the vendored ai-job-search LaTeX template.
2. **Render** → `lualatex` → PDF. Overflows one page?
3. **Fit loop (the filtering)** — if overflow: rank lines by (JD-keyword relevance,
   uniqueness, cover-letter dependency), cut the lowest first, re-render; repeat until it
   fits. Keyword-rich lines survive over generic ones — filtering never strips content
   the ATS needs. `log()` what was cut (no silent truncation).
4. **ATS check on the FINAL PDF** (the artifact that will be submitted):
   - `pdftotext` extracts the real text layer (reads it as a parser does, not visually).
   - contact (name/email/phone) present as literal text, not trapped in image/header.
   - sane reading order (no scrambled columns/tables).
   - keyword coverage scored vs THIS job's JD.
   - no garbled glyphs.
   Returns `{ats_score, contact_ok, reading_order_ok, keyword_coverage, missing_keywords, warnings}`.
5. **Layout verify loop** — re-inspect the rendered pages, apply targeted spacing/
   page-break fixes, re-render until clean.

A weak final ATS score is shown to the user *before* attaching, so they can toggle
different blocks and regenerate.

## Storage

New `resumes` table (via db.py, idempotent migration): `id, job_id, pdf_path,
blocks_used (json), ats_score, ats_report (json), created_at`. Each generation is saved
against its job, so every application records exactly which resume + ATS score was used —
the "what are we sharing" review the Application Agent depends on. Generated PDFs live
under `documents/generated/` (gitignored).

## API surface

- `POST /api/jobs/{id}/resume/suggest` → `{suggested_blocks, rationale}` (LLM block
  suggestion from the job's deep-rank + JD).
- `POST /api/jobs/{id}/resume/generate` body `{block_ids: [...]}` → renders + fits +
  ATS-checks, saves a `resumes` row, returns `{pdf_url, ats_score, ats_report,
  blocks_used, cut_lines}`. 409/clear error if MacTeX/`lualatex` is unavailable
  (actionable "install MacTeX" message — never a silent failure).
- `GET /api/jobs/{id}/resumes` → prior generations for this job.
- `GET /api/resumes/{id}/pdf` → serves the PDF.
- `GET /api/resume/segments` → the block manifest (for the toggle UI).

## Dashboard panel

On each job's detail: **"Tailor resume"** → calls `suggest` → shows blocks as toggles
(suggested ones pre-checked, with the rationale) → **Generate** → server runs the
pipeline → **inline PDF preview + ATS score + missing-keyword chips** → download / mark
as the resume attached to this application. Register warm (matches the Teal v2 tokens).

## Boundaries (deferred)

- **Cover letters are subsystem 4** — a separate next sprint (they research the company,
  not just the JD). This sprint is resume only. The fit-loop's "cover-letter dependency"
  ranking input is a placeholder until then.
- **Application Agent** (company-site auto-apply, review→submit) is the sprint after —
  it consumes this engine's saved resume + ATS score.
- No new resume *content* authoring — the engine selects/reorders existing blocks only.

## Testing

- **Renderer injected** (`render_pdf` callable) → tests pass a fake that returns a
  fixture PDF; no MacTeX needed. One optional live smoke test skipped when `lualatex`
  is absent.
- ATS check tested against small fixture PDFs (good + parse-hostile) — real `pdftotext`
  if present, else mocked.
- Block suggestion tested with a fake LLM returning a fixed block set.
- Fit-loop cutting tested deterministically (fake overflow signal → asserts lowest-
  relevance line cut first, keyword-rich line kept).
- db.py `resumes` table + queries follow the existing idempotent-migration + test
  pattern. Existing suite stays green.

## Non-goals

- Multi-page resumes, multiple templates, DOCX output.
- Auto-applying (Application Agent sprint).
- Editing block *content* in the UI (v1 selects/reorders; content edits happen in the
  source CV).
