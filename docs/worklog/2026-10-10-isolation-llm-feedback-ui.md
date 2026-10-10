# 2026-10-10 — Data/browser isolation, swappable LLM, feedback-driven UI

## Goal
Make the app usable for day-to-day applying: every write in one data folder, the agent in its own browser, the LLM
swappable by env, and a UI that only shows what produces feedback for the agent.

## What changed

### One data root (`src/job_dashboard/paths.py`)
- Everything the app writes lives under `data/` (or `$JOB_DASHBOARD_DATA_DIR`, also read from `.env`).
- Moved off `~/.career_agent`, `/tmp`, `~/.cache`: secrets → `data/secrets/`, portal state → `data/state/`,
  scratch screenshots/OTP → `data/tmp/`, HF + Chroma model caches → `data/cache/` (re-downloadable, skip in backups).
- Tests run against a throwaway data root (set in `tests/conftest.py`) and can never launch or touch Chrome.

### Isolated agent browser (`src/job_dashboard/agent_browser.py`)
- One Chrome, profile `data/browser/profile`, debug port 9333 (`AGENT_CDP_PORT`), launched on demand as a separate
  instance next to the user's everyday Chrome. All CDP consumers (job sources, hiring posts, apply agent, submit
  watcher, scripts) go through `ensure_running()`. `CAREER_AGENT_CDP_URL=off` falls back to Playwright Chromium.
- Windowless-Chrome fix: macOS keeps Chrome alive after its last window closes, and Playwright's attach then fails
  with `Browser context management is not supported`. `ensure_running()` opens a blank tab first.
- Playwright MCP (`.mcp.json`) profile and output also under `data/`.

### Swappable LLM (`src/job_dashboard/llm.py`)
- Single OpenAI-compatible Responses API client (`POST {LLM_BASE_URL}/responses`); every call site ported
  (`letter/draft.make_default_llm`, `resume_llm`, LinkedIn contacts/enrich). Env: `LLM_BASE_URL`, `LLM_API_KEY`,
  `LLM_MODEL`, `LLM_REASONING_EFFORT` (defaults to `none` for local Ollama), `LLM_NO_TEMPERATURE`, `LLM_TIMEOUT`.
- Tolerant JSON parsing (Ollama's json mode still wraps output in fences). Verified live against Ollama qwen3:14b.
- `apply/local_model.py` only starts/stops Ollama when Ollama is the configured provider.
- Live-model smoke tests are opt-in (`RUN_LIVE_LLM=1`).

### Embeddings
- `gte-base-en-v1.5`'s remote code breaks on transformers 5.x → switched to `Alibaba-NLP/gte-modernbert-base`
  (native, 8192 ctx, pinned revision). Model loads in the background (`LazyModel`) so the server starts in ~1.5 s.
- Fixed `cosine()` returning numpy float32, which sqlite stored as a BLOB (every embed score was unreadable).

### Feedback loop
- `match/preferences.py`: Skip (with a reason: role / level / location / company / tech / other) and Apply/Queue
  are recorded in `job_feedback`; learned weights re-rank `/api/jobs?sort=learned`, a company skip hides that
  company, and a one-line summary is injected into the deep-rank fit-judge prompt. Users can forget a preference.
- `api/feedback_routes.py`: `/api/inbox` (blocking questions with their form options, guesses to confirm, bank
  questions with which applications asked them and their rule help), `/api/jobs/{id}/feedback`, `/api/preferences`,
  `/api/explain` (plain-language meaning of a form question).
- Open questions now record the form's options so the inbox can offer one-tap answers.
- Tracker: failed rows carry `error_detail` (last exception line of the run log) and the UI shows
  "What happened / What to do" per stop reason (`frontend/src/queueReasons.js` `QUEUE_FIX`).

### UI
- New shell: four destinations — Needs you (one card at a time), Jobs (compact rows, Apply / Skip-with-reason,
  "Learned" chips, Sources toggles for logged-in boards), Applied (tracker), Memory (answers + résumé; tuning and
  retrieval stats folded away).
- Rule-based bank questions (e.g. "previously applied to this company?" = a company list) no longer render as a
  bare Yes/No. Every card has "What does this mean?" and "Type my own answer".
- Removed: stat tiles, donut, header art, filter sidebar, duplicates panel (`Feed`, `FilterBar`, `StatusPie`, ...).

## Verification
- Python: 1489 passed, 96 skipped, 1 failing — `tests/test_screening.py::test_prompt_keeps_projects_in_separate_blocks`,
  which already failed before this session.
- Frontend: 127 vitest tests pass; `vite build` ok. UI exercised in the browser pane on a throwaway demo data root.

## Open items
- `test_screening.py::test_prompt_keeps_projects_in_separate_blocks` (pre-existing failure).
- For local Ollama, raise the context length (~16k) in the Ollama app: hiring-post judging sends résumé-sized prompts
  and the Responses API has no per-call `num_ctx`.
- The desktop app's preview launcher is blocked by macOS's Documents-folder permission until it is granted; run the
  server from a terminal (`.venv/bin/python -m uvicorn job_dashboard.api.serve:app --port 8000`).
