# Application Agent — Design

## Purpose

Help the user apply to a job by **auto-filling the application form in their own
Chrome and stopping at Submit** for their review. Subsystem 5 of the master
design — it consumes the tailored resume (resume engine) and the optional cover
letter (cover-letter engine) and turns "I want to apply" into a mostly-filled
form the user only has to check and submit.

The work splits into two halves with a hard boundary between them:

- **Side A — the app (built this sprint):** knows *the user* and *the job*, and
  produces the answers. Reusable application profile, per-job package assembly,
  grounded screening-answer drafting, application tracking, and the "Apply"
  panel. Deterministic, testable Python + React. Never touches the career site.
- **Side B — the browser agent (a documented runbook, not app code):** knows
  *the page*. Opens the job URL in the user's Chrome (Claude-in-Chrome), maps the
  form's fields to Side A's answers, fills them, and STOPS at Submit. Never
  invents content, never submits.

Decisions fixed (user-confirmed 2026-07-31):
- **Interaction = browser auto-fill in the user's real Chrome, stop at Submit.**
- **Scope = known ATS first** (Greenhouse, Lever, Ashby, Workday) with a
  best-effort generic fallback.
- **Screening free-text answers = LLM-drafted (qwen), grounded, user edits.**
- **Cover letter is OPTIONAL** per application — attached only when the form has
  a slot for it, always user-toggleable; resume-only is a first-class outcome.

## Safety boundary (non-negotiable rails)

These are requirements, not preferences, and every task inherits them:

1. **The agent NEVER clicks Submit / final-apply / "confirm application".** It
   fills, stops, and hands control back for the user's review + click.
2. **Never** enters passwords, creates accounts, or solves CAPTCHAs. If a site
   requires login, account creation, or a CAPTCHA, Side B pauses and reports it —
   the user handles it.
3. Fills **only** from data the user saved in `application_profile` (plus the
   job's resume/letter/screening drafts). A field it cannot confidently map is
   **left blank and flagged**, never guessed.
4. **EEO / demographic / disability / veteran** questions are left untouched
   (nothing selected) for the user to answer.
5. Side B acts **only** on the exact job URL the user hands it; it never follows
   links off that page or navigates elsewhere.
6. **Two review gates:** (1) the user approves the assembled package in the
   dashboard before any browser action; (2) the user does a final on-page review
   before *they* click Submit.
7. Side A stores only what the user entered; no third party receives the
   profile. Screening drafts follow the same never-fabricate discipline as the
   cover letter (grounded in profile/research/resume; best-effort code check +
   authoritative human edit).

## Side A — app components

### Data model (db.py, idempotent migrations)

- `application_profile` (single-row, id=1): `full_name, email, phone, location,
  linkedin_url, github_url, portfolio_url, work_authorization (free text — the
  user's real status, e.g. "US: require sponsorship, no H1B; EU: authorized;
  India: citizen"), years_experience, willing_to_relocate (bool), notice_period,
  salary_expectation (nullable), updated_at`. Never guessed — user-set. Getter
  returns `None`/empty when unset.
- `applications` (per job): `id, job_id, resume_id (nullable), cover_letter_id
  (NULLABLE — optional), status ('prepared' | 'applied'), screening (json:
  [{question, answer}]), ats (nullable text — detected platform), applied_at
  (nullable), created_at`.

### Package assembly

`assemble_application_package(job_id) -> dict`:
- Pulls the `application_profile`, the job's most recent tailored `resume`
  (pdf path/url) if any, and the job's most recent `cover_letter` if any (marked
  **optional**). Returns `{profile, resume, cover_letter (nullable), job}`. Does
  not require a cover letter; resume-only and profile-only are valid.

### Grounded screening answers

`draft_screening_answer(job, question, profile_text, research, resume_text,
llm=None) -> {answer, flags}` in a new `apply/screening.py`, reusing the
cover-letter draft's Ollama seam and grounding discipline. Answers a single
page-specific free-text question from real data only; empty/uncertain →
general truthful answer, never invented specifics. Never raises.

### ATS field-maps (data, not logic)

`apply/ats_maps/*.json` (`greenhouse.json`, `lever.json`, `ashby.json`,
`workday.json`): each maps canonical field intents → the platform's typical field
labels/synonyms, e.g. `{"phone": ["Phone", "Phone Number", "Mobile"], "resume":
["Resume/CV", "Attach Resume"], "cover_letter": ["Cover Letter"], ...}`. A
`generic.json` holds cross-ATS label synonyms for the fallback. Loaded/validated
by `apply/ats_maps.py` (`load_ats_map(name) -> dict`, `detect_ats(url) -> str`).
Side B reads these to map page fields reliably.

### API

- `GET/PUT /api/application-profile` — read / upsert the profile.
- `GET /api/jobs/{id}/application-package` — the assembled package
  (`{profile, resume, cover_letter, job, ats_hint}`). 404 unknown job.
- `POST /api/jobs/{id}/screening-answer` `{question}` → `{answer, flags}`
  (grounded; Ollama down → truthful general answer, never 500).
- `GET /api/ats-map/{name}` → the field-map JSON (Side B fetches it), 404 unknown.
- `POST /api/jobs/{id}/application` `{resume_id?, cover_letter_id?, screening?,
  ats?, status}` → create/update the `applications` row (status `prepared` on
  package approval, `applied` after the user confirms submission). `GET
  /api/jobs/{id}/application` → the record or null.
- All injectable (fake profile/llm) so tests need no browser/LLM.

### Dashboard "Apply" panel (job detail)

- Shows the assembled package: profile summary, the resume to use, the **optional
  cover letter** (toggle — default follows "attach only if the form asks", so the
  toggle starts off and Side B turns it on when a slot is found), and a note
  listing what the agent will and won't do (the safety rails).
- **"Prepare application"** → creates the `prepared` record, shows a checklist,
  and the instruction to start the browser agent. **No auto-submit control.**
- After the user submits on the real site, **"Mark as applied"** → status
  `applied`, records resume/letter/screening used, and flips the job's status.
- Teal v2 tokens, reduced-motion. A visible, persistent "the agent stops at
  Submit — you send it" banner.

## Side B — browser-agent runbook (documented, not app code)

Written to `docs/application-agent-runbook.md`. Procedure the assistant follows
with Claude-in-Chrome when the user says "apply to job X":

1. Read the job's package + ats-map from Side A's endpoints.
2. Open the job URL in the user's Chrome. `detect_ats`; load its field-map (or
   generic). If login/account/CAPTCHA required → stop, report, hand to user.
3. Read the form (accessibility tree). Map each field via the field-map + label
   synonyms to a package answer. Fill mapped fields; upload the resume PDF; if a
   cover-letter slot exists and a letter is available, attach it (else skip).
4. For each free-text screening question: call `screening-answer`, show the draft,
   let the user edit, then fill.
5. **Stop at Submit.** Report a summary: fields filled, fields left blank/flagged,
   anything needing the user (login, CAPTCHA, EEO, ambiguous field).
6. The user reviews on-page and clicks Submit. On their confirmation, POST the
   `application` as `applied`.

The runbook restates the safety rails as hard stops.

## Testing

- `application_profile` + `applications` DB: idempotent migration + CRUD
  round-trip (nullable cover_letter_id, json screening), mirroring existing table
  tests.
- `assemble_application_package`: resume-only, +cover-letter, profile-unset cases.
- `draft_screening_answer`: fake llm → grounded answer; llm raises → general
  answer, no raise; empty research → no fabricated company specifics.
- `ats_maps`: each json loads + validates required intents; `detect_ats` on
  sample Greenhouse/Lever/Ashby/Workday URLs; generic fallback.
- API: profile get/put, package (resume-only + optional letter), screening
  (Ollama-down graceful 200), application create→get round-trip, 404s — all with
  injected fakes (no browser/LLM).
- Frontend: Apply panel renders package + optional-letter toggle + safety banner +
  "Mark as applied"; **no submit/auto-apply control** (asserted absent).
- Side B is assistant-driven — validated by a live manual run, not unit tests.
- Existing suite (241 pytest + 41 vitest) stays green.

## Non-goals (v1)

Auto-submitting; login / account creation / CAPTCHA solving; bulk/mass apply;
recruiter/HR contact scraping (Outreach sprint); non-Chrome browsers; editing the
ATS field-maps in the UI; a fully headless/unattended apply.
