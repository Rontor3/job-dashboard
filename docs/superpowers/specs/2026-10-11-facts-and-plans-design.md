# Facts and plans: tell once, answer every wording

Date: 2026-10-11 · Status: design, prototype benched · Supersedes the per-question answers of
`2026-09-26-question-bank-design.md` (the bank's wordings and matching survive; its per-entry answers become facts).

## 1. Problem

The question bank stores an answer **per question**. A question asked in a new shape needs a new entry even when
the information is already stored: "Rate your English" holds `Fluent`, yet "Are you fluent in English?" escalated
four times; your date of birth is stored, yet "Are you 18 or older?" escalated. Of 104 unanswered fields (63 distinct
questions, application_qa 2026-09-26 → 10-09) most had their answer in the database already. Re-asking the user what
they already told us is the failure this design removes.

**Goal.** The user states a piece of information once. Every later question that depends on it, in any wording and
any field shape (yes/no, option, number, text), is answered from it without asking again.

**Non-goals.** Résumé files (hand-made, never modified). Long free-text answers (stay in `longform/`). Changing the
submit gate.

## 2. Model

| Part | What it is | Written by | When |
|---|---|---|---|
| **Fact** | One typed, atomic value: `dob` (date), `english` level, `current_ctc` (money), `skills` (grid skill→years) … | The user, once (dashboard), or migrated from `application_profile` + bank answers | When information is first needed |
| **Operator** | A tested building block: `age`, `cmp`, `lookup`, `level_at_least`, `money`, `amount`, `contains`, `not/and/or` | Developers, in code (`memory/facts.py`) | Rarely: a new *kind* of question |
| **Plan** | Which operators to combine over which facts for one question, as JSON: `{"op":"cmp","cmp":">=","args":[{"op":"age","args":[{"fact":"dob"}]},18]}` | Claude Haiku via the logged-in CLI (`claude -p --model haiku`), not the API | Once per new wording |
| **Executor + formatter** | Run the plan locally; fit the value to the field (bool→Yes/No option, ordinal→option, money→"25"/"25 LPA", date→the field's format) | Code | Every fill |

Haiku never writes executable code and never sees a value: its input is the question, the field type/options, and
the **fact schema** (names, types, descriptions, grid keys). Values stay on the machine; PII never leaves it.

## 3. Storage (jobs.db)

```
fact       key PK | type | value_json | source (profile/you/migrated) | status (active/superseded) | updated_at
plan       id PK  | plan_json (canonical: two wordings meaning the same thing share one row) | out_type
           | status (proposed/confirmed/rejected) | author (haiku/seed/human) | confirmed_by (application_qa id) | created_at
wording    norm PK | text | vec (MiniLM) | plan_id                       -- replaces qbank_wording -> entry
fill_link  qa_id | wording | nearest_json (similar wordings + scores when filled) | user_choice (same/different)
           | plan_id | check (match/mismatch) | created_at
```

- `application_profile` keeps its columns; each column is exposed as a fact (no copy, no second source).
- Bank entries split: literal answers → `fact` rows; questions → `wording` rows pointing at a plan. Entries that only
  pointed at a profile column (`profile_ref`) become plans `{"fact": <column>}` — the duplicate goes away.
  Old rows are kept, marked superseded.
- **Grids.** `skills` = skill → years, rows pre-filled from `skills_pool` + the existing skill table; a skill absent
  from the grid is 0 and is added as a row the first time a form asks about it (no question to the user).
  `languages` = language → level (basic < conversational < professional < fluent < native).
  Both are edited on the Answers tab as Google-Forms-style grids.
- Demographics and legal facts (gender, ethnicity, veteran, disability, citizenship, non-compete, criminal record,
  relatives per company …) are ordinary facts: authorized autofill (2026-08-29), never re-asked.

## 4. Runtime flow (one field)

```
field ─► junk label? ─ yes ─► skip
   │
   ▼
wording cache hit (exact norm, or embedding ≥ HIGH with the same out_type) ─► run plan ─► format ─► fill
   │ miss
   ▼
Haiku compiles (question + field + schema) ─► one of:
   plan            ─► checks (§5) ─► run ─► fill, marked "new interpretation" in the pre-submit review
   NEW_FACT(k,t)   ─► ask the user for the FACT once (dashboard / Telegram), store it, then fill
   NOT_A_QUESTION  ─► skip
   │ CLI unavailable / login expired / timeout
   ▼
fallback: the current ladder ("guarded": dial-code + years rules, bank, rule mapper, top-k LLM only for real questions)
          fills marked likely; the wording is queued for compilation later
```

A run never blocks on Claude. Repeat wordings never call a model.

## 5. Checks — nothing unverified is filled

Before a new plan fills anything:
1. Every fact and operator it names exists; types fit (`level_at_least` on a level, `money` on money).
2. It uses at least one stored fact (a constant is a guess: `"Siemens" == "Siemens"` is rejected).
3. A yes/no field gets a boolean; an option field gets a value that fits one of its options.
4. Money compares only with money (a bare `3500` against a CTC has no unit → rejected).
5. A grid lookup without a default fails rather than inventing a value; only "years in X" defaults to 0.

Confirmation:
- **Submit review** (already human-gated): each new interpretation shows one line ("21+ → Yes, from date of birth").
  Approving the form confirms the plan; editing that field rejects it and stores the edit as a fact.
- **Typed answers** (dashboard reply, Telegram): the typed value is the reference — a plan is confirmed only if
  executing it reproduces what the user typed; otherwise the answer is stored as a new fact and the plan rejected.
- Optional cross-check: if the fallback ladder disagrees with a new plan, flag instead of filling silently.

## 6. Saving an answer on the dashboard

1. **Resemblance check** (local, instant, before save): nearest existing wordings with their current values —
   "Looks like: 'Are you at least 18?' → Yes  [Same question] [Different]". Same + a different value → conflict warning.
2. On save: background compile (Haiku), check against the typed answer (§5), store wording → plan or a new fact.
3. `fill_link` records the question, the nearest wordings and scores at fill time, the user's choice, the plan and
   the check result. Reports: duplicates (resembled + same value → merge), conflicts (resembled + different value),
   and the compiler's check-pass rate.

## 7. Migration (one-off, no input from the user)

1. Back up jobs.db. Build facts from `application_profile` and every answered bank entry (prototype: `facts.build`).
2. Compile every existing wording (343) with Haiku; each wording's current bank answer is its reference (§5) —
   matching plans are confirmed, mismatches are listed for review.
3. Pre-fill the skills and languages grids; list the facts the backfill reports missing.

## 8. Testing

- Unit: operators, executor, formatter, checks (`tests/career_agent/test_facts.py`).
- Bench: `scripts/answer_methods_bench.py` — 44 real unanswered fields with gold answers derived from stored data,
  junk labels that must be skipped, and facts that are genuinely missing (must come back as NEW_FACT, not a guess).
  Baselines (2026-10-11): current ladder 12 correct / 6 wrong; guarded 25 / 1; facts+plans with qwen3:14b as the
  compiler 20 / 10 (wrong logic: polarity, units, reversed comparisons).
- **Acceptance:** with Haiku as the compiler, 0 wrong and at least guarded's 25 correct; every remaining gap is a
  NEW_FACT or a skipped non-question.
- **Result (2026-10-11, Haiku via `claude -p`, ~8 s/compile):** prompt v1 20 correct / 1 wrong / 5 missed (too
  cautious: asked for facts a general one covers); v2 (general-covers-narrower rule) **26 / 1 / 1**. The wrong one is
  a formatter gap, not logic: "Pursuing/ Completed" → plan `degree_completed` (right) rendered "Yes" for a field that
  wants a word. The miss: "available for a virtual interview?" vs the stored text "Whenever Scheduled".
  Caveat: v2's prompt was tuned on these 44 cases — confirm on a held-out set (new misses) before relying on it.

## 9. Order of work

1. Haiku compiler in the bench (`compiled_haiku`) → acceptance numbers. *(done: 26/1/1; held-out check pending;
   formatter: a boolean into a non-yes/no field must map to the field's own words or escalate.)*
2. Tables + migration (§3, §7) behind the existing `QBankMemory` interface, so graph/boards/walk are unchanged.
3. Runtime compile on a cache miss + fallback (§4); checks (§5); review lines in the submit summary.
4. Dashboard: resemblance check + `fill_link` (§6); then the skills/languages grids.
