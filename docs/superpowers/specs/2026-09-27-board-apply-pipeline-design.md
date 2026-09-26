# Board apply pipeline — design

Date: 2026-09-27 · Status: approved in brainstorming, building

## Problem

`career_agent` fills company career sites (ATS). Jobs scraped from job boards — Naukri,
LinkedIn, Indeed, iimjobs, Instahyre, Wellfound — are applied **on the board itself**, and the
career-site pipeline breaks there. Live probes (2026-09-26/27) showed:

- The career-site drill (`page_prep.reach_application_form`) opened Naukri's
  `myapply/saveApply` URL as a page → "Something went wrong", yet **Naukri recorded the
  application** while the agent reported `submitted=False` (jobs 27059, 27065, 27052).
- On one-click boards the **entry click is the submission**, so `do_submit=False` is not a dry
  run there.
- Every board confirms an application through its **own network response**, and most send the
  screening questions as **JSON before the form renders**.

Full traces: memory `career-agent-board-probes.md`.

## Decision

One board pipeline alongside the career-site graph (not six agents, not a subgraph per board).
Boards differ only in **data** (a board profile) and in one of **two drivers**: `form` (one-click = a form with zero pages, wizard = several pages) and `chat` (Naukri).
Answers come from the existing shared ladder.

```
apply.py ── board_for(url)? ──no──► existing career-site graph (unchanged)
               │yes
               ▼
        boards.run_board(page, board, ctx)
          session_check → open → entry → questions → answer (shared ladder) → put → advance
          → submit gate → confirm (board's own response) → record
```

## Board profiles (data)

`board` nodes in `docs/career-agent/ats-graph.json`, loaded by `boards/profiles.py`:

| field | meaning |
|---|---|
| `id`, `domains` | `board:naukri`, host globs matched against the job URL |
| `archetype` | `form` \| `chat` (a chat board with no questionnaire behaves as a zero-page form) |
| `entry` | CSS selector of the apply control; `submits`: `yes` \| `no` \| `maybe` |
| `questions` | `{capture, path}` — URL fragment + JSON path of an upfront questionnaire (optional) |
| `confirm` | `{capture, path, match}` — URL fragment, JSON path and regex that prove "applied" |
| `logged_out` | URL fragments / selectors that mean we are not signed in |
| `challenge` | URL fragments / text that mean a bot challenge (hard stop) |
| `advance` | wizard button names (Next/Continue/Review), `final` = submit button names |
| `daily_cap` | per-board applications per day (RateLimiter `domain_day_cap`) |

Initial values come from the traces:

| board | archetype | entry (submits?) | questions | confirm |
|---|---|---|---|---|
| naukri | chat | `button.apply-button` (maybe) | `apply-workflow/v1/apply` → `jobs[0].questionnaire` | `apply-workflow/v1/apply` → `jobs[0].message` ~ `successfully applied` |
| linkedin | form | `[aria-label*="Easy Apply" i]` (no); interstitial "Continue applying" | page fields (shadow DOM) | `easyapply.submit` (status 200) |
| indeed | form | "Apply now" (no) | page fields on `smartapply.indeed.com` | graphql `SubmitApplication` → `submitApplication` present |
| iimjobs | form | "Apply" (yes) | — | `job/apply?jobcode` (200) or URL `/job/applied` |
| instahyre | form | "Apply now" (yes) | — | `candidate_matching/apply` → `success` true |
| wellfound | form | "Apply" (no); modal with location / relocate / note | modal fields | graphql `CreateJobApplication` |

## Components (`src/career_agent/boards/`)

| file | purpose |
|---|---|
| `profiles.py` | load board nodes; `board_for(url) -> dict \| None`; `json_path(obj, path)` |
| `signals.py` | pure: `is_logged_out`, `is_challenge`, `confirmed(board, responses) -> bool \| None` |
| `questions.py` | pure: questionnaire JSON → `Field` list (Naukri shape; Indeed later) |
| `drivers.py` | `form` and `chat` drivers sharing one interface: `questions(page, board, cap)`, `put(page, field, value)`, `advance(page, board) -> "next"\|"review"\|"final"\|"none"` |
| `run.py` | `run_board(page, board, ctx) -> result dict` — the pipeline above |

Shared-code change: `orchestrator/answering.py` extracts the answer ladder out of `graph.fill_node`
(`recall → semantic → map_screen → judge`) into `answer_fields(fields, ctx) -> (decisions, needs)`,
and the learn/feedback write from `human_gate_node` into `record_answers(fields, answers, ctx)`.
`fill_node` / `human_gate_node` call these — behaviour unchanged, now reusable by boards.

## Answers and the human gate

- Questions come from the questionnaire JSON when the board sends one, else from the visible
  form (existing `perception`, shadow-DOM aware). Each becomes a `Field`; `form_model` rules give
  it a purpose (years_experience, salary_expectation, notice_period, location, …).
- `answer_fields` runs the shared ladder. Anything left goes to `HumanLoop.collect`
  (Telegram / CLI) **before** the first irreversible click; answers are written back with
  `record_answers`, so "years with <skill>" is asked once across all boards.
- Naukri's own `prefillData` is used as the answer when the ladder has none (it is the user's
  own Naukri profile value).
- Unanswered **required** question after the human pass → stop `needs_human`, nothing clicked.

## Submit gate

- Irreversible click = the `final` button or the `entry` click when
  `entry.submits` is `yes`/`maybe`.
- It happens only if `do_submit` and (`autonomous` — the durable standing authorization — or
  `human.approve(card)` returns true). Otherwise stop `dry_run` **before** that click.
- Board jobs never go through `reach_application_form` (root-cause fix for the saveApply bug).

## Outcome

Result dict matches the career-site one (`url, job_id, submitted, stopped_reason, decisions,
pending_human`) plus `board`. `submitted` is **only** true when `confirmed()` sees the board's
own response; if the click happened but no confirmation arrived → `stopped_reason="unconfirmed"`
(never claimed as applied). `RateLimiter.record(board_id, map_outcome(...))`.

## Errors / stops

| stopped_reason | when | action |
|---|---|---|
| `logged_out` | login / sign-up screen | notify human to sign in in Profile 3; never create board accounts |
| `challenge` | reCAPTCHA / Cloudflare / unusual-activity | hard stop, board cooldown via RateLimiter |
| `daily_cap` | RateLimiter says defer | skip |
| `closed` | posting expired / not found | skip |
| `needs_human` | required answer missing after collect | stop before any irreversible click |
| `dry_run` | submit not authorized | stop before the irreversible click |
| `unconfirmed` | clicked, no confirmation response | report, don't mark applied |
| `no_entry` / `stuck` | entry control missing / wizard not advancing | stop |

## Testing

- Unit (no browser): profile loading + `board_for`, `json_path`, signals, Naukri questionnaire →
  Fields, `answer_fields` parity with the old fill_node path, submit-gate decisions in `run_board`
  with a fake page/driver.
- Browser fixtures (`RUN_BROWSER_TESTS=1`): a static HTML one-click page, a wizard page, a chat
  page whose apply call is mocked with Playwright `route()` — drive `run_board` end to end.
- Live: the user runs the CLI per board (Claude's own live submits are permission-blocked).

## Out of scope (later)

Indeed questionnaire JSON parsing (use page fields first), LinkedIn shadow-DOM Next beyond a CSS
locator, Wellfound free-text note quality, Naukri chat skip handling for optional questions.
