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
