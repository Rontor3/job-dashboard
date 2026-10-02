# Story answers — your own words for essay / founder-message drafting

Date: 2026-09-27 · Status: design approved, pending spec review
Builds on: `docs/superpowers/specs/2026-09-26-question-bank-design.md` (question bank)

## Problem

Work at a Startup (YC) applications are one founder-message box ("share something
about you, what you're looking for, or why {company} interests you"). The judgment
tier drafts it via `job_dashboard/apply/screening.py::draft_screening_answer`, and the
result is generic because:

1. The only "about you" input is `profile_to_text(profile)` (résumé facts), cut to
   1200 chars. There is nowhere to put the candidate's own motivation in their own words.
2. The job page / JD is passed as `resume_text` and labelled "RESUME EXCERPT" (800 chars),
   while company specifics are allowed only from `research.facts` (usually empty) — so the
   prompt forbids mentioning anything about the company.

## Goals

- The candidate writes a few guided long-form answers once; every essay-type field
  (founder message, "why us", motivation) is drafted from them + the job page.
- Drafts connect the candidate's words to what the company does, in a warm, specific tone.
- Truthfulness unchanged: no invented candidate facts; company details only from the job
  page or verified research; low-confidence drafts still flagged; submit/Send stays gated.

## Non-goals

- No new scraping (YC company pages, founder profiles) — job page text only.
- Story answers are never pasted verbatim into form fields.
- No YC-specific code path: any motivation / why-us field benefits.

## Design

### 1. Story entries in the question bank

Five seed entries in `data/qbank_seed.json`, `topic: "story"`, `atype: "text"`, no answers:

| id | question |
|---|---|
| `story_looking_for` | What are you looking for in your next role? |
| `story_why_startups` | Why do you want to work at an early-stage startup? |
| `story_proudest_work` | What work are you proudest of, and why? |
| `story_how_you_work` | How do you like to work (team, pace, ownership)? |
| `story_problems` | What kinds of problems excite you? |

Seeded with no extra wordings. `qbank.exact()` and `qbank.wordings()` exclude
`topic = 'story'`, so the matcher can never fill a form field from a story entry.

`qbank.story_text(conn) -> str`: answered story entries as
`"Q: <question>\nA: <answer>"` blocks joined by blank lines; `""` if none answered.

### 2. Dashboard

Answers tab: `story` is the first topic section, titled "Your story (used to write
essays)", and story entries use a multi-line textarea instead of a single-line input.
The existing entry save flow (`PUT /api/answers {entry_id, answer}`) is unchanged.
Story entries count toward "unanswered" (they need input).

### 3. Essay drafting

- `JudgmentContext` gains `story_text: str = ""`; `apply.py` sets it from
  `qbank.story_text(conn)`.
- `judge()` passes `ctx.story_text` to `draft_screening_answer(..., story_text=...)`.
- `screening._build_prompt` changes:
  - New block `IN THE CANDIDATE'S OWN WORDS` (story_text, up to 2500 chars), listed
    as a source for claims about the candidate alongside profile/résumé.
  - The `resume_text` argument (which carries the job page / JD) is relabelled
    `COMPANY & ROLE (from the job page)`, limit raised 800 → 2000 chars.
  - Rule 2 becomes: company specifics only if they appear in COMPANY & ROLE or
    VERIFIED COMPANY FACTS; never invent one.
  - New rule: connect what the candidate says they want/enjoy to what this company
    does; warm, specific, first person; 4–6 sentences.
- `check_grounding(answer, research, profile_text, job_text)`: `profile_text` argument
  becomes profile + story so claims taken from the story aren't flagged; `job_text`
  already includes the description.
- `draft_screening_answer` keeps `story_text=""` default so other callers are unaffected.

## Testing

- `qbank`: story entries seeded, excluded from `exact`/`wordings`, `story_text` format and
  empty case.
- `screening._build_prompt`: contains the own-words block and the COMPANY & ROLE label,
  respects limits, omits the own-words block when empty.
- `judge` forwards `story_text` (fake llm captures the prompt).
- Frontend: story section renders first with textareas; saving sends `{entry_id, answer}`.

## Known limits

- Tone/quality depends on the local LLM; measured the same way as other drafts
  (confidence + kept/edited review).
- Job pages with thin descriptions give thin company hooks (by choice: no extra scraping).
