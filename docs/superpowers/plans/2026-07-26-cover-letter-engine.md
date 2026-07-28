# Cover Letter Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Checkbox steps. Dispatch prompts in caveman style (project memory).

**Goal:** Per-job cover letter grounded in real company research (TinyFish, free), drafted by Ollama qwen2.5:14b in the candidate's voice, two-sided integrity (company claims trace to research; candidate claims to profile), rendered to PDF, reviewed in a dashboard panel. Never auto-sends.

**Architecture:** New `src/job_dashboard/letter/` package: `company_research.py` (TinyFish Search+Fetch → cited facts), `draft.py` (grounded qwen draft, reuses `resume_llm` Ollama adapter), `grounding.py` (best-effort unsupported-company-claim check). `db.py` gains a `cover_letters` table. Render reuses `resume/render.py`. API + a "Draft cover letter" panel mirror the resume engine.

**Tech Stack:** Python 3.11+, TinyFish HTTP (`api.search.tinyfish.ai` GET, `api.fetch.tinyfish.ai` POST, `X-API-Key`), Ollama qwen2.5:14b, lualatex (installed), pytest (HTTP + llm + renderer injected/mocked), React.

## Global Constraints

- **Two-sided grounding (integrity):** company claims must trace to the TinyFish research bundle; candidate claims to the profile/segments. Empty research → general letter, never invented company specifics. Best-effort code check + authoritative human review in the panel.
- **Research scope = role-relevant monetary/product impact** — not generic mission praise.
- TinyFish `X-API-Key` from env `TINYFISH_API_KEY` (`TINYFISH_HOST` overridable); never committed/logged. Any TinyFish failure → empty bundle, never raises; draft/API never 500 on it.
- Ollama reused via `resume_llm`'s adapter/`post` seam; llm failure → general-template letter, never raises.
- No test performs a real TinyFish/Ollama/network call except explicitly-skipped live smokes.
- Render reuses `resume/render.py` (injectable lualatex runner); PDFs under `documents/generated/` (gitignored). db.py only SQL.
- Never a send action anywhere (that is the later Application Agent, per-message confirmed).
- Existing suite (166) stays green.

---

### Task 1: `company_research.py` — TinyFish Search+Fetch → cited facts

**Files:** Create `src/job_dashboard/letter/__init__.py`, `src/job_dashboard/letter/company_research.py`; Test `tests/test_company_research.py`.

**Interfaces:** `ResearchBundle(facts: list[Fact], queries_used: list[str], empty: bool)`; `Fact(text: str, source_url: str)`; `company_research(company, role, jd_text, search=None, fetch=None, api_key=None) -> ResearchBundle`. `search(query, api_key) -> list[dict]` (default GET tinyfish search) and `fetch(urls, api_key) -> list[dict]` (default POST tinyfish fetch) injected; tests mock them. Builds 2–3 role-relevant impact queries, searches, fetches top URLs, extracts capped/deduped cited snippets. ANY error → `ResearchBundle([], [...], empty=True)` (never raises).

- [ ] Step 1 — failing tests (inject fake search/fetch):
```python
# tests/test_company_research.py
from job_dashboard.letter.company_research import company_research, ResearchBundle

def test_builds_bundle_from_search_and_fetch():
    def fake_search(query, api_key=None):
        return [{"url": "https://acme.com/impact", "title": "Acme impact"}]
    def fake_fetch(urls, api_key=None):
        return [{"url": urls[0], "content": "Acme's fraud platform cut losses 40% ($200M saved)."}]
    b = company_research("Acme", "ML Engineer", "fraud detection role",
                         search=fake_search, fetch=fake_fetch, api_key="k")
    assert isinstance(b, ResearchBundle) and not b.empty
    assert any("40%" in f.text or "200M" in f.text for f in b.facts)
    assert all(f.source_url for f in b.facts)

def test_empty_bundle_on_search_error_never_raises():
    def boom(query, api_key=None):
        raise RuntimeError("tinyfish down")
    b = company_research("Acme", "ML", "jd", search=boom, fetch=lambda u, api_key=None: [], api_key="k")
    assert b.empty and b.facts == []

def test_empty_bundle_when_no_results():
    b = company_research("Acme", "ML", "jd",
                         search=lambda q, api_key=None: [],
                         fetch=lambda u, api_key=None: [], api_key="k")
    assert b.empty
```
- [ ] Step 2 — FAIL. Step 3 — implement: query builder (role-relevant impact); default `search`/`fetch` using `requests` (lazy import) with `X-API-Key` and `TINYFISH_HOST` env; snippet extraction (split fetched markdown into impact-bearing sentences carrying $/%/funding/product cues, cap ~8, dedupe, attach source_url); wrap everything so any failure → empty bundle.
- [ ] Step 4 — PASS. Step 5 — live smoke skipif no `TINYFISH_API_KEY`: real `company_research` on a known company → bundle (≥0 facts), no raise; run if key present.
- [ ] Step 6 — commit `feat: TinyFish company-research adapter producing cited impact facts`.

---

### Task 2: DB — `cover_letters` table

**Files:** Modify `src/job_dashboard/db.py`; Test `tests/test_cover_letter_db.py`.

**Interfaces:** `save_cover_letter(conn, job_id, pdf_path, body, company_facts_used:list) -> int`; `cover_letters_for_job(conn, job_id) -> list[dict]`; `get_cover_letter(conn, id) -> dict|None`. Idempotent `_ensure_cover_letters_table` wired into `init_db`, mirroring `_ensure_resumes_table`.

- [ ] TDD (mirror test_resume_db.py): save → list round-trips `company_facts_used` json + `body`; get by id; unknown → None. Table `(id, job_id, pdf_path, body TEXT, company_facts_used TEXT, created_at TEXT)`. Commit `feat: cover_letters table + queries in db.py`.

---

### Task 3: `draft.py` + `grounding.py` — grounded qwen draft + guard

**Files:** Create `src/job_dashboard/letter/draft.py`, `src/job_dashboard/letter/grounding.py`; Test `tests/test_letter_draft.py`, `tests/test_letter_grounding.py`.

**Interfaces:**
- `draft_cover_letter(job, profile_text, research: ResearchBundle, writing_style, llm=None) -> {body, company_facts_used, flags}`. `llm(prompt) -> str` injected (default = a thin Ollama call reusing `resume_llm`'s `post`/model seam); never raises → returns a general-template body when llm/empty. Prompt: connect candidate REAL strengths → company role-relevant impact drawn ONLY from `research.facts`; voice from `writing_style`; reference a company fact only if in the bundle; empty bundle → general letter, no fabricated company specifics.
- `check_grounding(letter_body, research, profile_text) -> GroundingReport(unsupported_company_claims: list[str])`. Flags company-specific tokens in the body — named products, $/% figures, funding/round terms — absent from `research.facts`. Does not rewrite; surfaces for the human.

- [ ] Step 1 — failing tests:
  - draft with a fake llm returning a body referencing a research fact → body present, `company_facts_used` lists the fact; empty research + fake llm → body with no fabricated company name (assert the known fabricated token absent).
  - draft with llm raising → returns a general body (no raise).
  - grounding: a body claiming "$500M" not in research → `unsupported_company_claims` includes it; a body whose company claims are all in research → empty list.
- [ ] Step 2 — FAIL. Step 3 — implement draft (grounded prompt, injectable llm via resume_llm seam, never-raises) + grounding (regex for $/% + funding terms + capitalized product-ish phrases; cross-ref against research.facts text). Step 4 — PASS.
- [ ] Step 5 — live smoke skipif no Ollama: real qwen draft from a small fake research bundle → non-empty body, references a bundle fact; report the letter. Commit `feat: grounded cover-letter draft (qwen) + best-effort grounding guard`.

---

### Task 4: LaTeX letter render (reuse render_pdf)

**Files:** Create `src/job_dashboard/letter/render_letter.py`; Test `tests/test_letter_render.py`.

**Interfaces:** `LETTER_TEMPLATE` (clean single-column article-class letter: date, addressee block, body marker, signature) + `render_letter_pdf(body, out_dir, runner=None) -> Path` reusing `resume.render.render_pdf`'s injectable runner + `lualatex_path`.

- [ ] TDD: compose splices `body` into the letter template; render with injected fake runner → pdf path + composed .tex written; live smoke skipif no lualatex → real letter PDF. Commit `feat: LaTeX cover-letter render (article-class letter template, injectable runner)`.

---

### Task 5: API endpoints

**Files:** Modify `src/job_dashboard/api/app.py`; Test `tests/test_cover_letter_api.py`.

**Interfaces (inject a fake letter_engine so tests need no TinyFish/Ollama/LaTeX):**
- `POST /api/jobs/{id}/cover-letter/research` → `{facts, queries_used, empty}`.
- `POST /api/jobs/{id}/cover-letter/draft` → `{body, company_facts_used, flags, grounding:{unsupported_company_claims}}` (research + draft + guard; uses the job's stored strengths + description).
- `POST /api/jobs/{id}/cover-letter/generate` `{body}` → render + save `cover_letters` row → `{cover_letter_id, pdf_url}`; 503 if lualatex missing; 404 unknown job.
- `GET /api/jobs/{id}/cover-letters`, `GET /api/cover-letters/{id}/pdf` (FileResponse, 404 missing).
- `create_app` gains injectable `letter_engine=None` (default wires real modules). Graceful: TinyFish/Ollama down → research empty / general draft, never 500.

- [ ] TDD (TestClient, fake letter_engine): research/draft/generate/list/pdf shapes; generate persists (POST→GET round-trip); 404s; 503-no-lualatex; TinyFish-down → draft 200 with empty facts. Commit `feat: cover-letter API endpoints (research/draft/generate/list/pdf)`.

---

### Task 6: Dashboard "Draft cover letter" panel

**Files:** Create `frontend/src/components/CoverLetterPanel.jsx`; Modify `frontend/src/components/JobDetail.jsx`, `frontend/src/api.js`; Test `frontend/src/__tests__/cover_letter_panel.test.jsx`.

**Interfaces:** `api.js` adds `draftCoverLetter(id)`, `generateCoverLetter(id, body)`, `fetchCoverLetters(id)`. `<CoverLetterPanel jobId />` in the detail: "Draft cover letter" → draft → shows **cited research facts used** (read-only, with source links) + editable letter `<textarea>` (body) + **amber unsupported-claim flags** → user edits → Generate → PDF link. Teal v2 tokens, reduced-motion. **No send button.** Match the REAL backend response shapes (facts=[{text,source_url}], company_facts_used, grounding.unsupported_company_claims) — mock fetch with those exact shapes so the seam can't drift.

- [ ] TDD (vitest, real backend shapes): draft renders facts + editable body + flag chips; editing the body then Generate calls generateCoverLetter with the edited text; pdf link renders; no send control present. Then `npm run build`. Commit `feat: Draft-cover-letter dashboard panel (cited research, editable body, grounding flags)`.

---

### Task 7: live end-to-end (controller-driven)

- [ ] With `TINYFISH_API_KEY` set + Ollama up: browser → a real job → Draft cover letter → confirm real research facts (cited) + a grounded draft in the candidate's voice + any flags; edit, Generate → real letter PDF; pdftotext confirms body + that company claims trace to research. Screenshot. Ledger.
- [ ] Then: whole-branch review + finishing-a-development-branch.

## Not covered (spec non-goals)

Auto-send (Application Agent); `/interview` reuse; multi-template/DOCX; editing the research bundle in the UI.
