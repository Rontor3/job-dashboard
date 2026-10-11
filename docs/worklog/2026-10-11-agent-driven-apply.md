# 2026-10-11 — Agent-driven apply runs (build; live verification not started)

## Goal
The in-app agent owns each job application through tools:
- It reads the form DOM-first (fields, values, grounded suggestions) and decides the values.
- A script fills them and checks them; anything that fails goes back to the agent.
- Every answer carries a citation. Anything the agent composed is marked "written by the agent, not your words".
- A job's priority (low / normal / high / dream) decides whether those composed answers hold submit for review.
- When the agent can't go on, the run pauses with the tab still open and a clear Inbox card, and the queue moves on.

Spec: `docs/superpowers/specs/2026-10-11-agent-driven-apply-design.md`. ADR: `docs/adr/0002-agent-owns-apply-runs.md`.

## What changed
- **Python apply-session service.**
  - `src/job_dashboard/apply/session_actor.py`: one Playwright thread attached to the agent Chrome.
  - `session_steps.py`: start, reach, snapshot, fill, advance, submit and page text. It reuses the board drivers and
    checks from `career_agent/boards/run.py` as they are. `run_board` was **not** split, so the CLI loop is unchanged.
  - `session_service.py`: sessions, the one-browser lock (`agent_run.lock`), walls → skipped, pause with the tab
    open and at most `apply_max_open_tabs` tabs, submit gated by policy, Inbox cards and a Telegram ping.
  - `run_store.py`: the `apply_run` table and `jobs.priority`.
- **Routes:** `/api/apply-sessions/*` in `api/apply_session_routes.py`.
  - Start only works for a queued job, since queueing is what the user Confirms.
  - Resume is human-only.
  - `PUT /api/jobs/{id}/priority` records an Undo.
  - Queue settings gained `apply_engine`, `apply_priority_default`, `apply_hold_priorities`, `apply_max_open_tabs`,
    `autosubmit_skip_first_site` and `autosubmit_daily_cap`. That route is consequential, so the agent needs a Confirm.
- **Policy:** `autonomy.autosubmit_policy(..., agent_mode, hold)`.
  - Answers from grounded sources count as confirmed.
  - Agent-written answers (and LIKELY bank matches) block only at hold priorities.
  - `autosubmit_skip_first_site` waives the first-submit rule; it is meant for verification only.
- **Answer records:** `application_qa.agent_written` and `.citation`, written by `QARecorder.agent_answer`.
- **Queue:** with `apply_engine=agent`, `QueueRunner._run_agent` hands the job to the agent through `apply/agent_launch.py`
  (`POST /agent/runs`), then polls `apply_run`.
- **Agent:**
  - `agent/src/tools-apply.ts`: the `apply_*` tools, `set_job_priority` and `load_skill`.
  - `skills.ts`: skills from `docs/agent/skills/`, listed in the prompt.
  - `runs.ts` plus `POST /agent/runs`: a background session on the new `applier` profile.
  - `search_jobs` gained `source` and `india` filters.
  - Skills: `apply`, `linkedin`, `wellfound`, `himalayas`, `shortlist`.
  - Playbook (`docs/agent/system.md`) and `INIT.md` updated.
- **Frontend:** paused-run cards get Resume, Show tab and Skip (`Updates.jsx`), and the job panel gets a priority selector (`JobDetail.jsx`).

## Verified
- **Python:** `uv run pytest -q`: 1576 passed before the queue-settings change. After it, `tests/test_apply_session.py`
  (13 tests) and `test_queue_api.py` pass.
- **Agent:** vitest 23 passed, including `agent/test/apply.test.ts`, a background applier run over a real FastAPI; typecheck clean.
- **Frontend:** vitest 171 passed; typecheck clean.
- **Live services:** api, worker and agent restarted on the new code and the frontend rebuilt; `/api/apply-sessions/{id}` answers.
- **Agent Chrome:** logged in to LinkedIn and Wellfound.
- **Wellfound fetch:** 51 jobs (48 Easy-style "native").

## Not done / open
- **No live run yet.** Queueing the dry-run job (565, Recro) was blocked by the session's permission classifier.
  `apply_engine` is back on `script`. The 3 + 3 + 3 verification submits are still to do once the user allows queueing real applications.
- **LinkedIn fetch returned 0 jobs over 7 pages** (backfill). Not yet investigated.
- **Himalayas login** in the agent Chrome is unconfirmed.
- **The daily cap of 5** auto-submits would stop a 9-submit verification. Raise it for the verification, then revert.
- **Switches the verification needs:** Himalayas and external LinkedIn jobs land on company sites, which use the
  `autosubmit_career_site` switch, so it needs turning on alongside `autosubmit_linkedin` and `autosubmit_wellfound`.
- **Not built yet:**
  - the `apply_screenshot` fallback;
  - reattaching to a paused tab after an API restart (a resume starts fresh instead);
  - the Inbox shortlist card with per-job Veto (the `shortlist` skill uses `notify_user`);
  - a live eval scenario for applying.
- **Cosmetic:** `/api/queue/autosubmit` lists `daily_cap` and `skip_first_site` as if they were boards, because they share the `autosubmit_` prefix.

## Live runs (the user queued 3 jobs; monitored)
- **#59 Mercor (Himalayas):** started before `apply_engine` was switched, so it ran on the script engine and parked
  `no_advance_control`. It never went through the harness.
- **#106 Anthropic and #104 JPMorgan (Indeed, "Apply on company site"):** the queue → `/agent/runs` → applier-session
  handoff works. The agent loaded the skill, called start → reach, ended each run with a reason, and the queue
  recorded it. Three harness bugs turned up:
  1. **Wrongly skipped.** The board's apply control was missing, so the run was skipped as `no_entry`. A board without
     its own apply flow now carries on as a career site (`_enter_board` → `left_board`).
  2. **Duplicate Inbox cards.** The agent called `apply_skip` after the automatic skip and got a second card.
     `skip` is now idempotent.
  3. **Wrong diagnosis.** Indeed's "Apply on company site" opens a **sign-in dialog**. `dismiss_dialogs` closed it as
     noise, then a guessed URL 404'd, and the agent concluded "listing gone". Now:
     - a sign-in dialog is kept (`page_prep._is_login_dialog`, `login_dialog_open`);
     - the session's reach makes the first Apply hop itself and reports `account_needed`.

  Checked against the live page with start + reach only (nothing applied): `account_needed: "Apply on company site"
  asks you to sign in to the site first`.
- **Retry blocked.** Re-queueing #104 to rerun it end to end was blocked by the session's permission classifier.
- **Wrong reasons on the cards.** #106 and #104 still show the wrong reasons from before the fixes (`listing_gone`,
  `no_entry`). The real blocker is the Indeed sign-in in the agent Chrome.
- **Suite:** 1578 passed.

## Dialogs, focus, scrolling (from the Mercor run, #59)
- **What went wrong on Mercor.** "Full legal name" never filled because Mercor's "You've been referred!" modal was
  open. The modal keeps keyboard focus inside itself, so typing behind it went nowhere. The agent had no way to answer
  the dialog and wrongly told the user the field "only takes real keystrokes". With the modal gone, the same fill sticks.
- **Dialog classification.** New `career_agent/browser/dialogs.py` reads the top dialog and classifies it as captcha,
  login, consent, idle, apply_step or question. `session_steps.check_dialog` runs after reach, snapshot, fill and advance:
  - consent and idle dialogs are handled on the spot;
  - captcha and login dialogs are walls;
  - any other dialog goes to the agent as `dialog` (kind, text, buttons).
  - On the harness thread, `page_prep.dismiss_dialogs` leaves non-idle dialogs alone (the `LEAVE_DIALOGS` contextvar).
- **New tool `apply_dialog(job_id, button)`.** The route is `POST /api/apply-sessions/{id}/dialog`. It refuses submit,
  sign-in, sign-up, payment and delete buttons. `apply_fill` refuses fields under an open dialog.
- **Skill.** The `apply` skill gained a "Dialogs over the page" section: decline referral or promo codes the user didn't
  give, and pause on anything that commits the user to something new.
- **Scrolling.** Every snapshot slow-scrolled the page top→bottom→top and took a full-page screenshot, roughly ten
  times per page. That was the constant up-and-down the user saw. The harness now scrolls a page once per (url, step)
  and takes no debug screenshot (`snapshot_form(scroll=, shot=)`).
- **Focus.** Playwright's `new_page()` activates the tab, which raises Chrome. Harness tabs now open with CDP
  `Target.createTarget {background: true}`. The agent Chrome gains `--disable-background-timer-throttling
  --disable-renderer-backgrounding --disable-backgrounding-occluded-windows`, which take effect on its next launch.
- **Verified.**
  - Real-browser tests (`tests/career_agent/test_dialogs_browser.py`): a referral-style dialog reaches the agent,
    "Decline" is pressed, "Sign up" is refused; a field behind the dialog is detected; the background tab opens.
  - `uv run pytest -q`: 1596 passed. Agent vitest: 23 passed, typecheck clean.
  - api and agent restarted.
- **Open.** The paused Mercor tab is still open, but the API restart dropped its live session, so Resume opens a fresh tab.

## Mercor rerun: zero-size dialogs, focus everywhere
- **The referral dialog was still missed.** Mercor's `role="dialog"` element is a zero-size Headless UI wrapper, and
  the visible box is a fixed child. `dialogs.read` now counts a dialog as open when it or a descendant has a box. It
  skips nested dialogs and marks the top one `data-jd-dialog`, and `press` clicks inside that element. New browser test:
  a zero-size wrapper. On the live tab it read `question / "You've been referred!" / [Close, Decline, Yes]`.
- **The rerun (#59)** filled Full legal name, LinkedIn and the résumé. Country and GPA didn't stick, and it ended
  `skipped / account_needed`: Mercor's "application" is its expert-account onboarding (`work.mercor.com/onboarding`).
- **Focus, the rest of the way.** The scraper (`sources/cdp/session.py`) and the script engine
  (`career_agent/browser/runner.py`, which also called `bring_to_front`) still opened tabs with `new_page()`. The
  helper moved to `agent_browser.background_tab`, and all three callers use it. Playwright's Chromium screenshot (the
  dashboard's live view) doesn't activate the tab, so it was not the cause.
- **Verified.** `uv run pytest -q`: 1596 passed. The api and worker were restarted. The agent Chrome still needs a
  relaunch for the no-throttling flags.

## Speed (timed from the #59 run, then profiled on a local Mercor-style form)
- **Where the time went.** The first snapshot took 149s, the first fill 82s, and every Next click 52s.
- **Snapshot (149s → about 4s).** The question bank made several model calls per ambiguous field to build
  suggestions. The harness ladder now runs without a model (`build_ctx`: `QBankMemory(llm=None)`), so suggestions are
  exact or confident matches only. The agent judges the rest itself through `search_answers`.
- **Fill (41s → 9s on 8 fields); Mercor's Country boxes.** `filler._pick_combobox` read options from a listbox that
  was rendered but hidden, then waited out a 4s click on an option you can't see, twice per box. It never typed, so
  the value never stuck. It now reads and clicks `:visible` options only, and types when none are shown. New browser
  test in `test_filler_browser.py`. It fails without the fix.
- **Next (52s → at most about 28s, less when the page answers).** `advance` waited 2s plus up to 12s more on top of
  `BrowserDeps.click`, which already waits up to 25s for the page to answer. The extra wait now runs only for board
  drivers, whose click doesn't wait.
- **Agent Chrome** quit (macOS kept the windowless one from 2026-10-10 alive) and relaunched through process-compose,
  now with the no-throttling flags.
- **Verified.** `RUN_BROWSER_TESTS=1 uv run pytest -q`: 1679 passed and 1 failed. The failure,
  `test_top_down::test_a_div_combobox_is_perceived_and_filled_in_page_order`, also fails at HEAD in a clean worktree,
  so this work didn't cause it.
- **Blocked.** The auto-mode classifier refused queueing a job and the verification-only settings (career_site
  switch, `autosubmit_skip_first_site`, daily cap). `submit_history` is empty, so with the first-submit rule in force,
  every run holds at submit. The pool has no LinkedIn jobs.

## Verification runs (the user allowed queueing and the verification-only settings)
- **Settings for verification:** `autosubmit_career_site=1`, `autosubmit_skip_first_site=1`, `autosubmit_daily_cap=12`.
  The LinkedIn and Wellfound switches were already on. **Revert all three after verification.**
- **Wellfound 3/3 confirmed** by the board's own response: #570 Planso, #563 BDIPlus, #556 Simplismart.
- **Himalayas:**
  - Confirmed: #479 Irth (Workable, "Your application has been submitted") and #433 Dscout (Greenhouse, recorded by the
    submit watcher after the fixes below).
  - Not applied:
    - #218 Mactores: skipped, hCaptcha.
    - #441 Simbian: Zoho image captcha. The run paused; it should have skipped (fixed below).
    - #90 Luma: Rippling returned "Internal Server Error" on every submit; paused as stuck.
- **Fixes found while driving the runs:**
  - **The Wellfound dialog snapshot ran past 240s.** `FormDriver._in_dialog` waited out a 1.5s `evaluate` timeout
    for each of the 62 page-chrome controls under the modal. They're aria-hidden, so `get_by_role` matched nothing.
    It now counts first: 88.8s → 0.1s. Browser test added.
  - **A submit Greenhouse confirmed was read as unconfirmed.** The page says "We've officially received your
    application" and the title says "Thank you for applying". The confirmation patterns are widened and the tab title
    is included. Unit test added.
  - **Image captchas typed into a plain box** (a Zoho "CAPTCHA" field) now count as a captcha wall in the snapshot,
    so the run skips. Browser test added; the `apply` skill says the same.
  - **Parked agent runs were never watched for a submit.** `QueueRunner._run_agent` now registers the open tab with
    the submit watcher, as the script path does.
  - **The run's tab id was stale** after the Apply hop opened the form in a new tab. `steps.reach` re-reads it, and
    `ApplySessions.reach`/`pause` save it to `apply_run`.
  - **The submit watcher stayed broken after one failed attach.** `CdpTabs.__enter__` left Playwright started on its
    thread, so every later pass failed with "Sync API inside the asyncio loop". It now stops Playwright before
    re-raising.
  - **LinkedIn fetched 0 jobs.** Job search moved to server-driven UI (`/jobs/search-results/`, a React Server
    Components stream; no `voyagerJobsDashJobCards`). A text `location=India` returns "No results found". Fixed:
    - `search_url` adds `geoId=102713980`;
    - `_load` falls back to the rendered page: `[componentkey^=job-card-component-ref-<id>]` cards, and "About the
      job" plus the Apply link on the job page;
    - `CdpSession.read(js)` added (read-only);
    - page stride is 25.
    Unit tests added. A live run returned real jobs with full descriptions and apply URLs.
  - **The div-combobox perception test** (failing at HEAD) is fixed. The Zoho guard looked at the combobox's
    grandparent, `<html>` on a plain page, and saw every other field there. It now only skips inside a real wrapper
    that holds exactly one text box.
- **Restart hazard (open).** Restarting the agent mid-run makes Pi Durable resume the old session alongside a new
  one, and the two collide on the browser lock. Restart only between runs.
- **Verified.** `RUN_BROWSER_TESTS=1 uv run pytest -q`: 1688 passed, 0 failed.
- **More fixes from the second Himalayas batch:**
  - Himalayas reached 3/3 with #139 Tolken ("Your application was successfully submitted").
  - #389 Fusemachines: skipped, reCAPTCHA.
  - #121 Coinbase: paused; its last required question is a legal attestation.
  - **React-Select's hidden `requiredInput`** (`aria-hidden`, `tabindex=-1`) was perceived as a required "Select..."
    field. The agent filled the neighbouring field instead, and submit failed validation. It's now skipped in
    perception. Browser test added.
  - **Tabs of finished runs stayed open.** `_close_tab` closed only the current page, not the listing tab the Apply
    hop left behind. The session now tracks every tab it worked in (`ApplySession.tabs`) and closes them all. Test
    added.
- **LinkedIn fetch, live:** the 30-day backfill brought in 46 jobs (60 loads, then the cap; it resumes next run).
  The scheduled Refresh had skipped LinkedIn because the 09:35 zero-job run counted as a success (6h cooldown), so
  this fetch was run on its own.
- **Flaky test:** `test_hiring_refresh::test_background_refresh_api` failed once under load and passes alone. Untouched.

## Verification done: 3 confirmed submits per board
| Board | Confirmed submits |
|---|---|
| Wellfound | #570 Planso, #563 BDIPlus, #556 Simplismart (board response) |
| Himalayas | #479 Irth (Workable), #433 Dscout (Greenhouse), #139 Tolken |
| LinkedIn (Easy Apply) | #932 Zorba AI, #908 Par Marketing, #927 Infosys Finacle (board response) |

- **Not submitted:**
  - #121 Coinbase: paused; a legal attestation is yours to answer.
  - #90 Luma: paused; Rippling's server error on submit.
  - #441 Simbian: paused on a Zoho captcha (before the fix).
  - Skipped on captchas: #218, #389, #929 (Keka; the new captcha-field wall caught it).
- **LinkedIn fixes:**
  - **Yes/No radios.** Every radio carries the question as its `aria-label`, with "Yes"/"No" in a sibling `<p>`.
    Perception named the options after the question, and `_pick_radio` wasn't scoped to the question's group, so
    every "Yes" went to the first question. Options now take their own visible text (when the whole group shares one
    name, which is the question), and the group label keeps the question. `_pick_in_group` ticks the matching radio
    within its own `name`. Browser test added; it fails on the old filler.
  - **Résumé step.** LinkedIn lists every résumé ever uploaded (three named `Aditya_Kumar_Resume.pdf`, from 2021-22)
    and has an "Upload resume" button with no file input. #932 and #908 went out with "Aditya Kumar 24 resume.pdf"
    (first uploaded 7/29/2024): the agent picked it from the list. The snapshot now shows the upload button as a file
    field, suggested with the current résumé and filled through the native chooser (`upload_chooser`). Picking by
    name is a fallback, used only when exactly one entry has the name. #927 went out with the freshly uploaded
    current résumé. The `linkedin` skill says the same.
- **Settings reverted after verification:** `autosubmit_career_site=0`, `autosubmit_skip_first_site=0`,
  `autosubmit_daily_cap=5`. `apply_engine` stays `agent` (the user's choice to keep or go back to `script`).
- **Verified.** `RUN_BROWSER_TESTS=1 uv run pytest -q`: 1693 passed, 0 failed.
- **Open.**
  - The worker still runs the old `CdpTabs.__enter__`; the fix is live after its next restart (it was busy with
    Refresh).
  - Restarting the agent mid-run still collides with Pi Durable's resume.
- **Later.** The worker was restarted once Refresh finished, so the `CdpTabs` fix is live. The one-off LinkedIn fetch
  ran with `now` shifted forward to get past the cooldown, which stored `last_run_at` as 2026-10-13. It is corrected
  to the real time, so scheduled LinkedIn refreshes aren't delayed.
