# 2026-10-10: Agent-first INIT.md onboarding

## Goal
The app's workflow was opaque to its user: it wasn't clear where credentials come from, which model runs, or what
runs in the background. The fix is an agent-first playbook. When the user asks an agent to start the app, the agent
checks whether setup has been done and, on a first run, interviews the user for the credentials and inputs the app
needs and confirms the defaults.

## What changed
- `INIT.md` (new, repo root): the playbook. It covers deciding the case from `data/setup-state.md`, the onboarding
  groups A–H (toolchain, LLM choice, identity, Gmail, sources and logins, Telegram and Tailscale, extras, autonomy
  defaults), the state-file template, the start preflight, the background-activity disclosure, and a "where does
  this credential come from" table. Every fact was taken from the code (`llm.py`, `paths.py`, `config/settings.py`,
  `api/serve.py`, `api/app.py`, `qa_store.DEFAULT_SETTINGS`, `queue_runner.py`, `credential_provider.py`,
  `gmail_otp.py`, `gmail_draft.py`).
- `CLAUDE.md`: one pointer line that routes start, setup and "where does X come from" requests to `INIT.md`.
- **Single agent window** (user request in the same session: "everything in one Chrome window, agent work in a
  separate tab"). New `job_dashboard/start.py` launcher (`python -m job_dashboard.start`) serves the dashboard,
  then shows it as a tab in the agent Chrome. On a cold start it launches Chrome on the dashboard URL. If Chrome is
  already running, it focuses the existing dashboard tab or opens one (`agent_browser.show_tab`, via `/json/list`,
  `/json/activate`, `/json/new`). Apply runs already opened a tab in that window (Playwright's `Target.createTarget`
  without `newWindow`); `browser/runner.py` now also brings that tab to the front so the run is visible.
  `.claude/launch.json`, `README.md` and `INIT.md` now start through the launcher.
- The state lives in `data/setup-state.md`, which is gitignored with the rest of `data/`. It records choices and
  whether each secret is present, never secret values.

## Verification
Added unit tests: `tests/test_agent_browser.py` (start URL, focus existing tab, open new tab, unreachable) and
`tests/test_start.py` (cold start, warm start, server never answers). Full suite run; see the commit. Every env var, path, default and command in INIT.md was
checked against the source.

## Open items (found while mapping the code)
- `career_agent/browser/credential_provider.py` falls back to a hard-coded person's first and last name when
  `CAREER_AGENT_FIRST_NAME` or `CAREER_AGENT_LAST_NAME` is unset, so new ATS accounts would be registered under the
  wrong name. The fallback should be removed and the fields read from `application_profile`.
- Fixed in this session: `queue_runner.py` and `agent_routes.py` passed `--claude-assist` on every run. That used
  the user's own `claude` login and wrote transcripts to `~/.claude`, which breaks the isolation rule. It is now
  opt-in through `CAREER_AGENT_CLAUDE_ASSIST=1` in `.env`.
- Still writes outside the repo: Ollama model weights (`~/.ollama`; `local_model.py` starts the macOS app, which
  ignores `OLLAMA_MODELS`) and the uv and npm caches during setup. INIT.md §0 lists these and the workarounds.
- `gmail_otp.py`'s docstring has an example account tag taken from a specific person.
