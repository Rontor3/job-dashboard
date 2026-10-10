# 2026-10-10 — Agent-first overhaul: Inbox, bulk apply, memory across sessions, agent profiles and the council

## Goal
The user asked for a UX overhaul, not a UI one: the agent should learn about them and keep it; the app should feel
agent-first; they shouldn't have to learn job portals or click Apply thirty times; add a notifications tab fully
integrated with the agent; try several system prompts / agent profiles, including adversarial review. Design:
`docs/superpowers/specs/2026-10-10-agent-first-overhaul-design.md`.

## What changed
- **Backend:** `notifications.py` + `api/notification_routes.py` (Inbox feed, about-me read/write/facts);
  producers in `apply/queue_runner.py` (`announce`), `apply/submit_watch.py`, `mail_scan.py` (`_move` now
  notifies), `worker.py` (`announce_refresh`). `POST /api/queue/batch` (in `confirm.CONSEQUENTIAL`). `/api/jobs?ids=`.
  `paths.ABOUT_ME`, `change_entities.FILES["about_me"]`.
- **Agent:** `team.ts` (profiles, `applyProfile`, `makeConsult`), `tools-team.ts` (`get_about_me`, `remember`,
  `list_notifications`, `notify_user`, `dismiss_notification`, `consult_agents`), `about_the_user` prompt section,
  `/profile`, `GET /agent/profiles`, `POST /agent/sessions {profile}`, sessions record `profile`.
  Profiles `docs/agent/profiles/{scout,critic,advocate}.md`. Playbook: "Learning about the user", "The user
  shouldn't have to learn job portals", "Other agents".
- **Frontend:** Agent is the first tab with `TeamRail` (missions, profiles, nested council sessions) and a start
  screen; Inbox = needs-you cards + `Updates`; Jobs multi-select + `BulkBar`; Memory → About you (`AboutMe.jsx`);
  "Applied" renamed "Applications"; styles in `styles/agent-first.css`.

## Verified
- pytest: 1539 passed, 96 skipped (new `tests/test_notifications.py`).
- Agent: typecheck; 19 tests, incl. `test/team.test.ts` (profile session tools/prompt, a real council round-trip
  with the faux model, remember + notify_user).
- Frontend: typecheck; 154 tests (smoke updated for the Agent-first start, bulk apply, About you, missions).
- Running app restarted; screenshots at desktop and phone width (`data/tmp/screenshots/v2-*`); fixed the bulk bar
  spacing, phone overflow on the Agent tab and repeated "saved lately" lines found that way.

## Open items
- Submitting a reviewed, parked form from the dashboard (design needed: it touches the submit gate).
- Scheduled agents (Scout after each Refresh) and an end-of-session reflection pass.
- `db.py` was already over 500 lines (now 592); worth splitting the jobs query out.
- Re-queue #450, Refresh with LinkedIn, Himalayas profile: still the user's (permission).

## Follow-up (2026-10-11): review fixes
- Agents list: fixed badge column, so descriptions align (2-line clamp). Rail missions are compact one-liners.
- Agent tab fills the window (`100dvh` flex shell): editor and footer always visible, only the transcript scrolls.
  The empty session's start screen gained "Right now" (`agent/StartScreen.tsx`): waiting-on-you, queue and updates
  counts plus the latest updates, each linking to its tab.
- Inbox questions: the 16 choice questions in `qbank_seed.json` carry `options` (`qbank.choices`), sent with Inbox and
  Answers items. A choice saves on one tap and moves to the next open question; Back / Next and a list of every
  question beside the card; going back shows the saved answer and lets you change it; keys 1–9, ← →, Enter, Esc.
- Verified: frontend 157 tests (new: auto-advance + back, keyboard, jump list), feedback/QA pytest, screenshots
  in both themes at 1440×900.

## Follow-up (2026-10-11): a smarter Inbox, readable themes, plain language
- Profile readiness (`profile_intel.py`, `api/profile_routes.py`, `ProfileReadiness.jsx`): a percent of what forms
  ask that the agents know, must-haves called out, "You're good to go" at 85% with every must-have. A new résumé is
  read into the gaps by itself (résumé, candidate profile, essay bank, and LinkedIn through the agent Chrome when
  enabled; `linkedin/own_profile.py`), every write logged with Undo.
- Inbox asks only what matters: questions real applications asked, the qbank must-haves, and missing profile
  must-haves (notice period, pay, years, work authorization; saved through `/api/profile/facts`). Answers are staged
  until Submit; skips are snoozed 30 days. Typed answers are read by the model (`/api/answers/interpret`): cleaned,
  other facts they imply filled, and any request in them sent to the agent.
- A reload keeps the tab (`#<tab>` in the URL). Agents and sessions show their full text, with a hover card
  (`agent/Tip.tsx`) for what each agent may touch; `/agent/profiles` returns `power` and `tools`.
- Theme: a softer paper-grey day palette (no near-white glare; text ≥ 4.5:1) and higher-contrast dark text
  (`tokens.css`); new styles in `polish.css`. The Agent header is one quiet bar: who you're talking to, what it does,
  tool count with a hover for what's loaded. The conversation reads in the sans font; tools and code stay monospace.
- Playbook: talk like a person; never show group letters, file names, tool names or field keys.
- Verified: pytest (profile/feedback/QA/notifications), agent typecheck + 19 tests, frontend 160 tests + typecheck,
  a live autofill (50% → 71%), screenshots in both themes.
- Open: plain-language Tuning, a shorter Your Story.

## Follow-up (2026-10-11): Jobs by company, and questions only some jobs ask
- Jobs are grouped by company (`JobGroups.jsx`), in rank order of each company's best opening: one card per company,
  one line per opening (title, location, age, fit, Apply, Skip); a one-opening company is a single line. The header
  ticks every open role there. Strong-fits-only and a flat list are toggles; "Show 60 more" pages the list.
- Company details (`company_details.py`, `api/company_routes.py`, entity `company` with Undo): referrer, relative,
  applied / interviewed / worked there before, set once per company; `db.get_job` merges them under the job's own,
  so the question-bank rules see them on every opening. Agent tool `set_company_details`.
- Situational questions (`situational.py`): a JLPT level for jobs in Japan, a CEFR level for German / French roles,
  an IELTS / TOEFL score, publications for research roles, a portfolio for design roles, a clearance, a driving
  licence: active when one of your live jobs triggers it (location, or an explicit language requirement). Each gets
  a bank entry (wordings embedded), joins readiness ("For your jobs") and the Inbox with which jobs asked. Agent tool
  `get_readiness`. The scan is cached until jobs, scores or the queue change (0.8 s → under 1 ms).
- Verified: full pytest (1548 passed), frontend 163 tests + typecheck, agent typecheck + 19 tests, screenshots.
