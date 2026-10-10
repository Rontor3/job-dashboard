# 2026-10-10 — Per-job apply details for company-specific questions

## Goal
"Needs you" asked "Were you referred by a current employee?", "Who referred you?" and "Do you have relatives
or close friends working at this company?" as *answer once, reused everywhere* cards. These answers depend on
the company, so one global answer is wrong. The user chose: default **No** (someone applying through the
portal almost never has a referral), with a way to give per-application details beside Apply.

## What changed
- **New rule `job_detail`** (`career_agent/memory/qbank_rules.py`). It resolves `referred`, `referrer_name`,
  `relatives_at_company`, `applied_before`, `interviewed_before` and `worked_before` from the job's
  `apply_details`:
  - each flag is No unless set;
  - `referred` is Yes when a referrer name is present;
  - `referrer_name` returns the name, otherwise the page's escape word, otherwise a flag.

  `RuleCtx` gained `entry_id` so one rule can serve several entries. The rule is in `NO_INPUT_RULES`, so these
  entries never become "Needs you" cards.
- **Seed** (`qbank_seed.json`): the six entries use `job_detail`. Four of them previously used
  `company_in_list`, and the two referral entries had no rule.
- **Storage**: new column `jobs.apply_details` (JSON). `get_job` (what the agent run reads) and `job_detail`
  return it parsed, and `set_apply_details` writes it.
- **API**: `PUT /api/jobs/{id}/apply-details`, validated by pydantic (`referrer` ≤120 chars, plus four booleans).
- **UI**: new `ApplyDetails.jsx` (a referrer input, four toggle chips, Save / Save & apply), opened by a
  **Details** button beside Apply in the Jobs list and in the job drawer.
- **Live DB** (not code): backed up to `data/backups/jobs-2026-10-10-before-qbank-clear.db`. Cleared the test
  answers `referred`, `applied_before` and `interviewed_before`, and set `rule='job_detail'` on the six entries.

## Verification
- New tests:
  - rule behaviour and seed rules (`tests/career_agent/test_qbank_rules.py`);
  - DB round-trip and API, including 404 and 422 (`tests/test_db_apply_columns.py`);
  - UI save-and-apply (`frontend/src/__tests__/apply_details.test.jsx`).
- Frontend suite: 23 files pass.
- Python suite: everything passes except `tests/test_screening.py::test_prompt_keeps_projects_in_separate_blocks`,
  which fails the same way on the unchanged tree. `tests/career_agent/test_get_job.py` was updated for the new field.
- Ran the dashboard on a separate port:
  - `/api/inbox` no longer lists the per-company entries;
  - the Details form renders beside Apply;
  - Save round-trips with no console errors.

## Follow-up: job location reaches the rules
`db.get_job` returned no `location`. Every apply run therefore gave `local_or_escape` an unknown city, and it
flagged "Where will you be working from?" even for jobs in your local cities. `get_job` now returns `location`.
A new test in `tests/career_agent/test_get_job.py` loads two jobs from a real DB and resolves `work_location`
to the home address for Noida and to "relocating" for London. Full suite: 1500 passed, plus the one screening
failure that was already there.

## Open items
- `tests/test_screening.py::test_prompt_keeps_projects_in_separate_blocks` was already failing and is unrelated.
- `db.py` was already over the 500-line guideline before this change.
