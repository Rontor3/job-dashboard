# Career Agent — Phase 3B: Real-Form Hardening (Design)

**Status:** Approved 2026-08-28
**Branch:** `career-agent-phase3b`
**Depends on:** Phase 3A multi-page orchestrator (merged to `main`)

## Motivation

Phase 3A's multi-page walk was validated only on clean local fixtures. A live
DRY-RUN (2026-08-28) against real data-scientist application forms exposed a
batch of gaps. On a Greenhouse form (Formation Bio) the walk correctly filled
email/phone/location/LinkedIn, escalated unknowns, detected Submit, and stopped
without submitting — but also:

1. **First + Last name both filled with the full name** — "First Name" and
   "Last Name" both classify as `full_name`.
2. **Option/boolean fields filled with prose / `"True"`** — work-authorization
   filled with a paragraph, "willing to relocate" filled literally `"True"`,
   the sponsorship question mis-mapped to `work_authorization`.
3. **Résumé never attached** — the walk's `map_screen` has no file /
   `resume_upload` handling.
4. **Greenhouse label association fails** — several real inputs perceived with
   empty labels → auto-escalated.
5. **Education silently dropped** — under `.jd_env` (no PyYAML), `load_segments()`
   raises `ImportError`, and a broad `except` in `load_candidate_profile`
   swallows it, dropping all education with no error.
6. **Country unmapped** (minor).

JPMC/Oracle CX never reached the gate (SPA rendered only the site shell), so it
is a **separate track**, out of scope here.

## Goal

The multi-page walk fills real ATS forms (verified live on Greenhouse)
correctly and truthfully, staying **LLM-free** (semantic judgment remains
deferred to Phase E).

## Global Constraints

- **LLM-free.** No qwen3 / Claude calls. Ambiguous cases escalate to the human,
  they are never guessed.
- **Truthful answers.** Work-authorization answers must never claim authorization
  the candidate does not hold (see Component 2).
- **Boundaries held (from Phase 3A):** attestations are never auto-ticked;
  a select/radio is never filled with a value that is not one of its options;
  dry-run never submits; the walk still stops on any gate whose handler is not
  `proceed` (captcha AND OTP) with `stopped_reason=gate:*`.
- **No PII in git.** The résumé PDF is rendered into gitignored `data/resumes/`.
- **Reuse, don't fork.** Résumé PDF rendering reuses the dashboard's existing
  `render_layout_pdf` / `render_pdf`; file upload reuses the Phase-1 filler.

## Canonical Résumé Source

A single layout version drives **both** the extracted `CandidateProfile` **and**
the attached PDF, so the data filled and the document attached never disagree.

- Selected by `apply.py --resume-version`, default `Rakshit_Singh_draft1` (a
  stable named version). `__working__` (the live auto-saved draft) is a valid
  override for the latest edits.
- The profile is extracted from that version's layout blocks (Phase 3A
  `load_candidate_profile`); education comes from the fixed segment library.
- The attached PDF is rendered from the **same** version (Component 3).

## Components

### 1. First / Last name split
**Files:** `browser/form_model.py`, `orchestrator/profile_resolver.py`

- Add purposes `first_name` and `last_name`. Their matching rules are ordered
  **before** `full_name` so "First Name" → `first_name` and
  "Last Name" / "Surname" / "Family Name" → `last_name` (never `full_name`).
- The resolver derives them from the profile: if `contact` carries explicit
  `first_name` / `last_name`, use those; otherwise split `full_name` — first
  whitespace token → `first_name`, the remainder → `last_name`. A single-token
  name yields that token as `first_name` and an empty `last_name` (escalated
  by the required-unknown rule if the field is required).
- No DB schema change.

### 2. Standard answers + option coercion
**Files:** new `orchestrator/standard_answers.py`, `orchestrator/screen_review.py`,
`browser/form_model.py`

New purposes recognized by the matcher: `visa_sponsorship`, `prior_contact`
(relationship / referral / "know anyone at"), plus reuse of the existing
`work_authorization`. For these three purposes, `map_screen` routes through
`standard_answers.answer(purpose, label)` **instead of** the plain
`profile_resolver.resolve` (which would return the raw contact string).
`answer` returns a canonical answer string, or `None` to escalate:

- `visa_sponsorship` → `"Yes"` (candidate would need a visa for onsite/relocation
  roles).
- `prior_contact` → `"No"`.
- `work_authorization` → **jurisdiction-aware**: scan the field label for a
  country. India → `"Yes"`; a named non-India country (US/USA/United States,
  UK, Canada, etc.) → `"No"`; **no country named → `None` (escalate)** — the
  walk must not blanket-claim authorization it cannot verify.

**Option coercion** (in `screen_review.map_screen`): given a canonical Yes/No (or
other enum) answer and a field's options, select the option whose normalized
text matches the answer — e.g. answer `"Yes"` matches an option containing the
token `yes` / `true`; `"No"` matches `no` / `false`. Matching is
case-insensitive and token-based, not substring-loose. **If no option matches →
escalate** (never blind-fill). For a free-text (non-option) yes/no field, fill
the canonical answer directly.

This replaces the Phase-3A behavior where a scalar/boolean profile value was
filled verbatim into an option field.

### 3. Résumé upload in the walk
**Files:** `orchestrator/screen_review.py`, `apply.py`, `orchestrator/browser_deps.py`

- At walk start, `apply.py` renders the PDF for the chosen `--resume-version`
  via the dashboard's `render_layout_pdf(layout, segments=load_segments(),
  render_pdf=render_pdf, out_dir=data/resumes/)`, obtaining a file path. A
  `--resume-pdf PATH` flag overrides with a specific pre-built file. The
  resolved path (or `None`) is threaded into the walk.
- `map_screen` handles `purpose == "resume_upload"` or `kind == "file"`: if a
  résumé PDF path is set → emit an `upload` decision (reuse the Phase-1 filler's
  upload action via `apply_decisions`); otherwise escalate the field.
- If rendering fails (e.g. LaTeX unavailable) and no `--resume-pdf` override is
  given, the path is `None` → file fields escalate; the walk still runs.

### 4. Robust label perception
**Files:** `browser/perception.py` (`_INPUT_JS` `labelFor`)

Extend label resolution, after the existing `label[for]` / wrapping `<label>` /
`<fieldset><legend>` / `aria-label` / `name` chain, to also try:
- `aria-labelledby` → concatenated text of the referenced element(s);
- a nearby label-like element — the closest preceding sibling or an ancestor's
  leading text node that visually labels the input (Greenhouse renders the
  visible label as a separate element, not a `<label for>`);
- `placeholder` as a last resort.

Goal: real, fillable inputs no longer arrive with empty labels (which forced
auto-escalation). Disabled/readonly inputs are still dropped (Phase 2 behavior).

### 5. Education / YAML robustness
**Files:** `memory/candidate_profile.py`, `.jd_env` (dependency)

- Add `PyYAML` to `.jd_env` so `load_segments()` (which imports `yaml`) works
  under the browser venv, restoring education extraction there.
- In `load_candidate_profile`, narrow the education `except` so a real failure
  is **visible**: catch `(ImportError, FileNotFoundError)` specifically and emit
  a one-line warning (stderr) naming the cause, instead of a bare
  `except Exception: pass` that silently drops all education.

### 6. Country (minor)
**Files:** `browser/form_model.py`, `orchestrator/profile_resolver.py`

- Map a "Country" field (`country` purpose) to a value derived from the
  contact's `location` (the trailing country token, e.g. "Mumbai, India" →
  "India") when unambiguous; otherwise escalate. No new profile field.

## Data Flow

```
--resume-version ──► load_candidate_profile ──► CandidateProfile (profile + education + skills)
        │
        └────────► render_layout_pdf ──► data/resumes/<version>-resume.pdf ──► resume_pdf path
                                                                                   │
per screen:  snapshot_form ──► map_screen(form, profile, resume_pdf) ──►┐         │
                                 ├─ direct profile value (name split, contact)    │
                                 ├─ standard_answers(purpose,label) + option coerce│
                                 ├─ resume_upload/file ──► upload(resume_pdf) ◄─────┘
                                 ├─ attestation ──► flag (never valued)
                                 └─ unknown/required/no-option ──► escalate (human.collect)
                              ──► apply_decisions (fill/select/check/upload)
                              ──► advance / detect-change / gate-stop  (unchanged)
```

## Error Handling

- Rendering failure → `resume_pdf = None` → file fields escalate; walk continues.
- Missing PyYAML → warning + empty education (no crash); after Component 5 it is
  installed so this is a defensive fallback, not the normal path.
- No matching option for a coerced answer → escalate (never blind-fill).
- Work-authorization with no determinable country → escalate.

## Testing / Validation

**Unit tests (LLM-free, no browser):**
- Name split: "First Name" / "Last Name" resolve to first-token / remainder of
  `full_name`; explicit contact `first_name`/`last_name` win.
- `standard_answers`: sponsorship→Yes, prior_contact→No; work_auth India→Yes,
  US→No, no-country→None.
- Option coercion: "Yes" → option "Yes, I am authorized"; "No" → "No"; a
  canonical answer with no matching option → escalate.
- Résumé-upload decision: file field + path → upload action; file field + no
  path → escalate.
- Label extraction: a synthetic Greenhouse-like DOM (label as a sibling /
  `aria-labelledby`) yields a non-empty label (perception unit test).
- YAML-missing path: `load_candidate_profile` warns and returns empty education
  instead of raising.

**Live validation (manual, `.jd_env`, dry-run):**
- Re-run the instrumented Greenhouse dry-run (Formation Bio). Expected: First and
  Last name split correctly; sponsorship = Yes; work-auth answered per
  jurisdiction or escalated; résumé attached (upload decision on the file
  field); no empty-label auto-escalations; education present; `stopped_reason =
  reached_submit_dry_run`; nothing submitted.

## Out of Scope

- **Oracle CX / JPMC SPA handling** (settle, entry path, email-first flow) — a
  separate track.
- **Phase E LLM judgment tier** for novel free-text questions ("Why do you want
  this job?") — those continue to escalate.
- **Per-application tailored PDF generation** — the walk attaches the résumé for
  the chosen version as-is; tailoring is the dashboard's existing job.
```
