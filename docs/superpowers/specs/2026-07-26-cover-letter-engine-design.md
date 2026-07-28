# Cover Letter Engine — Design

## Purpose

Generate a **per-job cover letter grounded in real company research**, in the candidate's
voice, reviewed in the dashboard before use. Subsystem 4 of the master design
(`2026-07-12-job-dashboard-design.md` §4). Consumes the same job + profile the resume
engine uses; produces the second artifact the later Application Agent presents for the
user's approve-then-send flow.

Decisions fixed (user-confirmed 2026-07-26):
- **Research source = TinyFish** (free Search + Fetch endpoints; better free tier than
  Tavily/Bright Data for this). Injectable HTTP seam so it's swappable.
- **Grounding scope = role-relevant company IMPACT only** — concrete **monetary or
  product impact** the company has made or uses, tied to the role. No generic
  "I admire your mission" filler.
- **Draft model = Ollama `qwen2.5:14b`** (reused, local, free).
- **Surface = dashboard panel** ("Draft cover letter") on the job detail, mirroring the
  resume panel.
- **Never auto-sends** — draft → user reviews/edits → user sends (send is the later
  Application Agent, always per-message-confirmed).

## Integrity model (two-sided grounding — the marquee guarantee)

Parallel to the resume engine's never-fabricate rule, extended to company facts:
- **Company claims:** every company-specific statement in the letter must trace to the
  TinyFish research bundle (a fetched source). No company claim qwen can't point to.
  If research is thin/empty, the letter stays general (role + candidate strengths)
  rather than inventing a product, funding round, or milestone.
- **Candidate claims:** every candidate-experience statement must trace to the profile /
  resume segments (reuse the resume engine's segment-integrity discipline). No invented
  experience.
- Best-effort code checks + the **authoritative human review** of the draft in the panel
  before it's used (same honest framing as the resume guard). qwen is prompted to ground
  strictly and to mark any claim it can't source.

## TinyFish research (new grounding layer)

`company_research(company, role, jd, search=None, fetch=None) -> ResearchBundle` in
`resume/company_research.py` (or a new `letter/` package):
- **Search** (`GET https://api.search.tinyfish.ai?query=…`, header `X-API-Key`): a few
  targeted queries for role-relevant impact, e.g. `"{company} product"`,
  `"{company} revenue funding milestone"`, `"{company} {top role-keyword}"`. Free tier:
  30/min.
- **Fetch** (`POST https://api.fetch.tinyfish.ai {"urls":[...]}`, `X-API-Key`,
  `format=markdown`): pull the top few result URLs → clean markdown. Free: 150/min.
- Returns `ResearchBundle(facts: list[{text, source_url}], queries_used, empty: bool)` —
  a deduped, capped set of source-cited impact snippets.
- `search`/`fetch` HTTP callables injected; tests mock them (no real TinyFish/network).
- `TINYFISH_API_KEY` from env (`TINYFISH_HOST` overridable). Any TinyFish failure →
  empty bundle (never raises); the draft then stays general.

## Draft (Ollama qwen2.5:14b)

`draft_cover_letter(job, profile_text, research: ResearchBundle, writing_style, llm=None)`:
- Prompt grounds qwen: write a concise cover letter connecting the candidate's REAL
  strengths (from `profile_text` / resume segments + the job's stored deep-rank
  strengths) to the company's role-relevant impact **drawn only from `research.facts`**;
  match the candidate's voice from `writing_style` (`03-writing-style.md`); reference a
  company fact only if present in the bundle; if the bundle is empty, write a strong
  general letter with no fabricated company specifics.
- `llm` injected (default = the Ollama adapter, reused from `resume_llm`); never raises →
  degrades to a general-template letter.
- Returns `{body, company_facts_used: [{text, source_url}], flags: [...]}`.

## Grounding guard (best-effort code check)

`check_grounding(letter_body, research, profile_text) -> GroundingReport`: flags
company-specific claims (named products, dollar/percent figures, funding/round terms)
in the letter that don't appear in `research.facts`, and surfaces them as
`unsupported_company_claims` for the user to verify/cut. Does not silently rewrite —
the human decides. (Mirrors the resume guard's best-effort + human-authoritative model.)

## Render + storage

- Render: a LaTeX **letter** template (single-column, clean, ATS-safe like the resume
  article template) → PDF via the existing `render_pdf` (injectable runner; live only on
  MacTeX, which is installed).
- `cover_letters` table (db.py, idempotent migration): `id, job_id, pdf_path, body,
  company_facts_used (json), created_at`. PDFs under `documents/generated/` (gitignored).

## API + dashboard panel

- `POST /api/jobs/{id}/cover-letter/research` → `{facts, queries_used, empty}` (TinyFish).
- `POST /api/jobs/{id}/cover-letter/draft` `{}` → `{body, company_facts_used, flags,
  grounding: {unsupported_company_claims}}` (research + draft + guard).
- `POST /api/jobs/{id}/cover-letter/generate` `{body}` (user-edited) → renders PDF, saves
  a `cover_letters` row, returns `{cover_letter_id, pdf_url}`. 503 if lualatex missing.
- `GET /api/jobs/{id}/cover-letters`, `GET /api/cover-letters/{id}/pdf`.
- Panel ("Draft cover letter" on job detail): Draft → shows the **cited research facts
  used** + the editable letter body + any **unsupported-claim flags** (amber) → user
  edits → Generate PDF → download / attach. Teal v2 tokens, reduced-motion. Never a
  send button (that's the Application Agent).

## Testing

- TinyFish search/fetch injected/mocked (no network); one live smoke skipped without
  `TINYFISH_API_KEY`.
- Draft llm injected (fake) — deterministic; one live smoke skipped without Ollama.
- Grounding guard tested: a letter claiming an unsourced product/figure → flagged; a
  fully-sourced letter → clean.
- Render uses the injectable runner (no MacTeX in CI); one live PDF smoke.
- db `cover_letters` table follows the existing idempotent-migration + test pattern.
- Existing suite (166) stays green.

## Non-goals (deferred)

- Auto-sending (Application Agent sprint — always per-message user confirmation).
- The vendored `/interview` company-prep reuse (bonus, later).
- Multi-template / DOCX; editing the research bundle in the UI (v1 shows it read-only).
