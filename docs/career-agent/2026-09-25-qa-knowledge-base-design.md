# Q&A knowledge base, per-application questions, retrieval analytics — design

## Problem

The agent's memory of your answers (`learned_answers`, the semantic vault) can
only be changed by answering a Telegram prompt mid-run. From the dashboard you
cannot see what the agent knows, which questions it could not answer for a given
application, why a generated answer was wrong, or whether retrieval is helping.

Three facts about today's code drive the design:

- **Nothing per-application is persisted.** `run_log.result_json` holds only
  `escalated_labels`. The question, answer, source and LLM context for each
  field are discarded after the run.
- **Weak generated answers are filled anyway.** In `orchestrator/judgment.py`
  `judge()`, an answer carrying a flag is appended to `answered` and merely added
  to `flagged`. There is no numeric quality signal, only boolean flags
  (`general_fallback`, `unsupported_company_claims`).
- **Retrieval returns only the winner.** `AnswerMemory.recall` and the semantic
  vault's match report the chosen answer, not what was considered, at what
  score, or what was rejected by the `_MIN_OVERLAP` / `_MATCH_DISTANCE` gates.

## Scope

In scope:

1. Record every field decision per application (`application_qa`).
2. An **Answers** tab: view, add, edit, delete your answers.
3. Under a Tracker row: open questions only, with a reply box that teaches memory.
4. LLM self-reported confidence with a threshold; below it the answer is not filled.
5. Retrieval analytics: what was retrieved, what it answered, whether it was right.

Out of scope:

- Editing `ingredients.json` from the dashboard. It stays read-only: CLAUDE.md
  requires its `source` text be quoted verbatim.
- A dashboard-blocking reply. Telegram stays the live channel.
- A separate LLM grading call (confidence is reported in the same call).
- Job fetching (CDP sources) and hiring-signal extraction: separate specs.
- Dropdown / option / combobox picks: only free-text generation gets a confidence.

## Where answers live (unchanged)

- `learned_answers` (sqlite + FTS5): short answers. Essays are deliberately never
  stored here.
- Semantic vault (ChromaDB `behavioral_qa`): meaning-matched Q&A with a confidence
  that becomes autonomous after 3 approvals; an edit resets it to 0.
- Both are written together by `MemoryRouter.dispatch("RECORD_FEEDBACK", ...)`.
  The dashboard writes through that same call so the dual-write logic stays in one
  place.
- `ingredients.json`: facts about you used to draft essays. Not an answer store.

## Data model

### `application_qa` (new, in `jobs.db`)

One row per field per run.

| Column | Meaning |
|---|---|
| `id`, `job_id`, `run_id`, `created_at` | identity. `run_id` = the `run_log` row id |
| `qkey`, `label`, `kind`, `purpose` | the question (`qkey` = normalized label, same as `learned_answers`) |
| `answer` | the value filled, or the drafted answer if not filled |
| `source` | `recall`, `semantic`, `rule`, `judgment`, `orchestrator`, `human`, `skipped` |
| `status` | `filled`, `needs_answer`, `answered` |
| `confidence` | 0-100 from the LLM, or NULL (unknown) |
| `basis` | one-line reason the LLM gave |
| `context_json` | exactly what the LLM was given: prompt, JD excerpt, profile text, company research facts, résumé text, ATS notes |
| `unsupported_claims` | JSON list from the existing deterministic claim check (evidence only) |
| `retrieval_kind` | `purpose`, `label_exact`, `fts_fuzzy`, `semantic`, `rule`, `llm`, `none` |
| `retrieved_qkey`, `retrieval_score` | matched memory entry and its score (token overlap or cosine distance) |
| `candidates_json` | top few candidates considered, including gate-rejected ones |
| `outcome` | `kept`, `edited`, `unanswered` |

Indexes on `(job_id, status)` and `qkey`.

### `agent_settings` (new)

Key/value. `answer_confidence_min` default `60`. The agent reads it at run start.

## Agent changes (`career_agent`)

1. **Confidence in the same call.** `draft_screening_answer()` (in
   `job_dashboard/apply/screening.py`) prompts for JSON `{answer, confidence, basis}`
   and returns `{"answer", "flags", "confidence", "basis"}`. Additive: the existing
   dashboard screening-answer endpoint keeps working.
2. **Threshold gate in `judge()`.** If `confidence` is below `answer_confidence_min`,
   the answer is not appended to `answered`; the field falls into `still_need`, so
   the live Telegram prompt still fires as today, and a `needs_answer` row is
   written. Malformed JSON or missing confidence = unknown = treated as below the
   threshold: an untrusted answer is never filled silently.
3. **Retrieval metadata.** `AnswerMemory.recall` and the semantic vault's match
   additionally return per-field metadata (kind, matched key, score, candidates).
   Existing return values and callers are unchanged.
4. **Recording.** `fill_node` and `human_gate_node` write `application_qa` rows for
   every decision (recalled, rule, generated, human-answered, skipped). Writes
   never raise into the run: a failure is logged and the run continues.
5. **Outcome.** The submit-time read-back that `record_corrections` already does,
   plus dashboard/Telegram edits, set `outcome` to `kept` or `edited`.

## API (`job_dashboard/api/qa_routes.py`, new router)

- `GET /api/answers?q=` merged list of learned answers + vault entries (one logical
  entry per question), with `confidence`, `approvals`, `autonomous`, `updated_at`,
  `asked_in` (count of distinct jobs from `application_qa`).
- `POST /api/answers`, `PUT /api/answers/{qkey}`, `DELETE /api/answers/{qkey}`:
  go through `MemoryRouter`, updating both stores. An edit resets vault confidence
  to 0 (existing rule).
- `GET /api/answers/{qkey}/applications` jobs that asked this question.
- `GET /api/jobs/{id}/questions` open (`needs_answer`) rows for that job, with
  confidence, basis, and context.
- `POST /api/jobs/{id}/questions/{row}/reply` saves the reply to memory (short
  answers: both stores; essays: semantic vault at confidence 0 plus the application
  row only, preserving "essays never in `learned_answers`"), sets `status=answered`.
- `GET /api/retrieval/stats`, `GET /api/retrieval/recent` analytics (below).
- `GET/PUT /api/agent-settings` for the threshold.
- `GET /api/ingredients` read-only.

All endpoints degrade to empty results if ChromaDB or a table is missing; none 500.

## Dashboard

- **Answers tab.** Search, add, edit, delete. Columns: question, answer, purpose,
  autonomous or not (with approvals), last updated, **asked in N applications**
  (click for the job list). The threshold control and a read-only ingredients
  section live here.
- **Tracker row expands inline.** Clicking a row opens a panel directly under it
  instead of the side drawer (drawer stays reachable via a "Details" link). It
  holds the step trail and stuck-page screenshot and run log (already built) plus
  **Questions**: open ones only, each with confidence, basis, a "context used"
  disclosure, and a reply box. Once answered, a question leaves the Tracker and
  lives only in the Answers tab. The row shows an open-questions badge count.
- **Retrieval section (Answers tab).**
  - Hit rate per retrieval tier vs. fall-through to LLM or to you.
  - Wrong-retrieval rate (retrieved, then edited) and which memory entries cause it.
  - Recent retrievals: question asked, entry retrieved (with score), answer used,
    outcome.
  - Score vs. outcome, for tuning `_MIN_OVERLAP`, `_MATCH_DISTANCE` and the
    confidence threshold from real data. Also average confidence of edited vs.
    approved answers.

## Reply flow

Saving a reply teaches memory. The next run of that job (existing "Apply with
agent") fills it via recall. Telegram remains the live prompt; the dashboard is the
after-the-fact and queued channel.

## Error handling

- Endpoints degrade to empty, never 500, when the vault or a table is missing.
- Recording failures never abort a run.
- Editing/deleting an entry that exists in only one store updates that store and
  reports which were touched.
- Concurrent edits: last write wins (single user), `updated_at` shown.

## Testing

- Unit: confidence parsing (valid, malformed, missing = unknown), `judge()` routing
  below-threshold answers to `still_need` with fake LLMs, retrieval metadata from
  `recall`, outcome derivation.
- API: answer CRUD keeps both stores in sync (temp sqlite + temp Chroma dir),
  reply saves and flips status, stats aggregation on seeded rows, graceful
  degradation.
- Frontend: Answers table and edit, expandable Tracker row showing only open
  questions and the reply box, retrieval section rendering.

## Phasing

- **Phase 1:** `application_qa` recording, confidence + threshold gate, Answers tab
  CRUD with "asked in N", Tracker inline open-questions with reply.
- **Phase 2:** retrieval metadata capture and the Retrieval analytics section.
  (Phase 1 records the tier and answer used; Phase 2 adds candidates and scores.)

## Known risks

- A 14B model rating its own answer in the same call tends to be overconfident;
  the default of 60 will need tuning. Scores are stored with outcomes precisely so
  the threshold can be set from your own data.
- The deterministic claim check is evidence only; a fully grounded but off-topic
  answer is caught only by eye via "context used".
