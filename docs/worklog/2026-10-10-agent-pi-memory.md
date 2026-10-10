# 2026-10-10 — Agent tab as a pi session, Memory redesign, embedding model in the worker

## Goal
User feedback after trying the in-app agent:
- the embedding model still loaded in the api;
- Memory had too many items with no organisation, and "History" made no sense there;
- the Agent tab was hidden (clipped off the nav) and felt like a chatbot. They want it first, and a full pi
  experience: slash commands, reloading, everything a pi session can do.

## What changed

### Embedding model → worker
- `job_dashboard/worker_jobs.py`: Refresh and the hiring-post refresh run in the worker. They are the only users of
  the embedding model.
  - The api writes `request='start'` to a `worker_job` row.
  - The worker starts the job on its thread and writes back status and a heartbeat every tick.
  - The api routes answer with the same shapes as before, plus `worker` and `queued`.
- `serve.py` builds the app with `in_worker=True` and no longer creates a model, a LinkedIn fetcher or a role judge.
- The hiring refresh never blocks the api any more, even without `background=true`.
- `LazyModel` now loads on first use, not at construction. The worker shares one copy between Refresh
  (`default_pipeline_runner(..., model)`) and the hiring refresh (`linkedin/hiring_job.py`).
- The Refresh button says when it is waiting for a worker that isn't running.

### Agent tab: a pi session in the browser
- **First tab.** `.app` is wider (1000px; 1200px on the Agent tab), so the nav no longer clips a tab.
- **Transcript** (`Thread.tsx`, `Markdown.tsx`):
  - prompts, then the agent's markdown, built as elements and never as HTML;
  - thinking folded until Ctrl+T;
  - each tool call shows its name and args with its result output, collapsed to 6 lines until Ctrl+O, plus change
    lines with Undo and widgets in place;
  - live tool output, retries, compaction, aborted runs and errors.
- **Editor** (`Editor.tsx`), with pi's keys:
  - Enter steers while busy; Alt+Enter queues a follow-up; Shift+Enter adds a new line;
  - Up/Down walk the history, kept in localStorage;
  - Alt+Up takes queued messages back; Esc stops, and queued text returns to the editor;
  - Shift+Tab cycles thinking; Ctrl+L picks a model; Ctrl+C clears;
  - `/` opens a filtered command menu: Tab completes, Enter runs.
- **Commands.** The service side is `agent/src/commands.ts`; the rest run in `AgentTab.tsx`.
  - Pickers and panels: `/model` (the endpoint's `/models` list, pinned per session), `/resume`, `/tree`, `/session`
    (stats), `/hotkeys`, `/settings`.
  - Session commands: `/thinking`, `/new`, `/name`, `/fork` (branch before a chosen message, which goes back in the
    editor), `/clone`, `/compact [instructions]`.
  - `/reload` re-installs the extension and re-reads the prompt files and templates.
  - Output and data: `/copy`, `/export [md|jsonl]`, `/changes` (the change log, now in words, with raw actions hidden
    by default), `/login` (the LLM key box).
  - Prompt templates come from `data/agent/prompts/<name>.md` (`$1…$9`, `$@`).
- **Startup header** (context files, tool count, prompts) and a **footer**: session, state, ↑↓ tokens, cost,
  context % of the window, model and thinking level. The editor border colour follows the thinking level.
- **Thinking.** Models declare `reasoning: true`, so `/thinking` sends `reasoning.effort`, and "off" sends `none`.
  - Sessions start at `LLM_REASONING_EFFORT`, or `medium` when it's unset.
  - Probed on the Qwen endpoint: no effort means its default (`xhigh`); `none` turns thinking off; `low`, `medium` and
    `xhigh` work; `high` and `minimal` get a 400 that names the supported values. That 400 shows in the transcript.
- **Playbook** (`docs/agent/system.md`): act, then stop. No greetings, closing offers or unprompted questionnaires.
  Onboarding runs only when asked.

### Memory
- Segments: Answers · Your story · Résumé · Tuning. History moved to `/changes` in the Agent tab.
- Answers has a topic rail with answered/total counts. "To fill" comes first and gathers every unanswered entry.
- Rows are compact (question · answer · asked N×); clicking one opens the editor, wordings, approvals and Remove.
  Unanswered rows are always editable.
- Search covers every topic and groups the hits.

## Verification
- **Python:** `tests/test_worker_jobs.py` (new, 4 tests) plus the refresh, hiring, worker, change-log and qa suites:
  53 pass.
- **Agent:** 13 tests pass, including new `commands.test.ts`: templates, name, thinking, clone and fork with the
  faux model.
- **Frontend:** 147 tests pass, including new `agent_tab.test.jsx`:
  - steer vs follow-up;
  - the slash menu and Tab completion;
  - server commands;
  - templates in the menu and prompt history;
  - panels;
  - tool-call rendering with folded thinking and collapsed output;
  - markdown safety;
  - export.

  `answers_tab.test.jsx` was rewritten for the rail.
- **In the browser** on `./jobdash start` with the real model:
  - Agent is the first tab;
  - the `/` menu and `/session` work;
  - `/new` and a question streamed with medium thinking, folded;
  - the worker answers `/api/refresh/status` (`worker: true`).

## Open items
- Logged-in LinkedIn and Himalayas: see the next worklog entry.
