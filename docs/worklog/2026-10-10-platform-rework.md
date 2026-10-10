# 2026-10-10 — Platform rework (in-app agent, step 2)

## Goal
Step 2 of `docs/superpowers/specs/2026-10-10-in-app-agent-design.md`: mise + pnpm workspace + process-compose +
`./jobdash`, split out the `worker`, a live `config` table, and remove the legacy launcher, `local_model` and
`setup.sh`.

## What changed
- **Toolchain, inside the repo.**
  - `./jobdash setup | start | dev | stop | test`.
  - `setup` fetches mise `v2026.10.6` into `.mise/` (mise.run). `MISE_DATA_DIR` etc. point there.
  - `mise.toml` pins Node 22.22.3, Python 3.12.15, uv 0.7.12, pnpm 10.34.6 and process-compose 1.122.0. It also
    sends the uv and npm caches to `data/cache/`.
  - Root `pnpm-workspace.yaml` (store in `.pnpm-store/`) and `package.json`. `frontend/package-lock.json` is
    replaced by `pnpm-lock.yaml`.
- **Processes (`process-compose.yaml`).**
  - `api` runs on :8000 and is health-gated on the new `/api/health`.
  - `worker` and `browser` start after the api is healthy. `browser` does not restart.
  - `ollama` is optional and disabled by default.
  - `process-compose.dev.yaml` runs Vite on :8000 with the api behind it on :8001, so the user sees one address
    either way.
  - The Hono `agent` process arrives in step 3. Until then the api serves the built UI.
- **Worker (`job_dashboard/worker.py`).**
  - The worker now runs the apply queue, the submit watcher and the daily mail scan, which were api threads before.
  - The api hands start and pause to the worker through a `queue_control` row in jobs.db
    (`apply/queue_control.py`, `QueueControl` has the QueueRunner surface). The worker writes the status back with
    a heartbeat, and `/api/queue` reports `worker: false` when the heartbeat is stale.
  - `/api/apply-agent/status` also shows a run the worker is doing.
- **One agent run across processes.** `AgentRunState` takes `data/state/agent_run.lock` and passes the locked fd to
  the career_agent child. The lock lives exactly as long as the run, whichever process started it.
- **One mail scan across processes.** It uses a lock file in the same way. The last result is kept in
  `agent_settings.mail_last_result`, so the api's status shows the worker's daily scan.
- **`config` table** (`job_dashboard/config.py`).
  - Holds the non-secret `LLM_*` settings plus `AGENT_CDP_PORT` and `AGENT_CHROME_PATH`.
  - A table value wins; the environment is the fallback. Values are copied from the `.env` file (not the shell)
    once, at api/worker start (`env.load_app_env`).
  - The `llm.config()` LLM client and `agent_browser` read it live.
  - `GET /api/config` and `PUT /api/config/{key}` validate the value. The response says `restart: "browser"` where a
    change needs a restart; nothing restarts automatically.
- **Removed.**
  - `start.py` → `python -m job_dashboard.agent_browser` (the `browser` process: it execs Chrome in the
    foreground, or brings the dashboard tab forward if Chrome is up).
  - `apply/local_model.py`: the app no longer starts or quits Ollama.
  - `scripts/setup.sh` and `tests/test_start.py`.
- Docs: `CLAUDE.md`, `INIT.md` (toolchain, start, and where LLM settings live now), `README.md`, `.env.example`,
  `.claude/launch.json`.

## Verification
- New tests:
  - `tests/test_config.py` (precedence, migration from `.env` only, live reload in `llm`, API).
  - `tests/test_worker.py` (start/pause hand-off, stale heartbeat, api doesn't run the queue, cross-process agent
    lock).
  - `tests/test_mail_api.py` (cross-process scan lock and result).
  - `tests/test_agent_browser.py` (browser process).
- Full suite: 1510 passed, 96 skipped. 1 failure, `test_screening.py::test_prompt_keeps_projects_in_separate_blocks`,
  which also fails on the base commit (`a300231`) and is unrelated. Frontend: 128 passed.
- `./jobdash setup` ran clean. Nothing was written under `~` (checked `~/.local/share/mise`, `~/.cache/mise`).
- `./jobdash start -t=false`: api healthy and `/api/queue` reports `worker: true`. `.env` LLM settings were migrated
  (`/api/config` source `config`). The browser process brought the existing dashboard tab forward. `PUT` and clear
  of `LLM_TIMEOUT` worked. The mail status showed the worker's scan result.
- `./jobdash dev`: Vite on :8000 served the UI and proxied `/api` to :8001. `./jobdash stop` cleaned up.
- Reviewed with `/code-review` (high). Fixed 8 of 10 findings. Two were left as is:
  - The default LLM is still local Ollama, though nothing starts it any more.
  - `/api/config` uses the global data-root DB, by design.

## Open items
- The embedding model still loads in the api (the spec puts it in the worker). The api's hiring and QA routes call
  it in-process, so moving it needs an api→worker call.
- The UI doesn't show `worker: false` or the `restart` notice from `PUT /api/config` yet (step 4, Agent tab).
- process-compose prints debug lines about a missing config under `~/Library/Application Support`. It only reads
  there.
- Step 3 (agent service) is next.
