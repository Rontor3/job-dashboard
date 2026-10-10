# Job Dashboard — Claude Code config

Two coupled subsystems in one repo, sharing `data/jobs.db`:
- **`src/job_dashboard/`** — scrape jobs, match, render résumés, profile store, API/extension (the "front half").
- **`src/career_agent/`** — autonomous job-application form-filler (the "back half"); reuses `job_dashboard`'s profile store, LLM, résumé rendering, and screening.

The dashboard produces jobs + profile; the agent consumes them to apply. This file is a small **index** — query the stores below on demand; don't inline them.

**Starting / setting up the app:** when the user asks to start, run, set up or reconfigure the app — or asks where a credential comes from, which model runs, or what runs in the background — follow `INIT.md` first. It checks `data/setup-state.md` and runs the onboarding interview if setup hasn't been done.

## Rules

- Do what has been asked; nothing more, nothing less
- NEVER create files unless absolutely necessary — prefer editing existing files
- NEVER create documentation files unless explicitly requested
- NEVER save working files or tests to root — use `/src`, `/tests`, `/docs`, `/config`, `/scripts`
- ALWAYS read a file before editing it
- NEVER commit secrets, credentials, or .env files
- NEVER add a `Co-Authored-By` trailer to user commits unless this project's `.claude/settings.json` has `attribution.commit` set (#2078). The Claude Code Bash tool may suggest one in its default commit-message template — ignore it. `Co-Authored-By` is semantic authorship attribution under git/GitHub convention; the tool is the facilitator, not a co-author.
- Keep files under 500 lines
- Validate input at system boundaries
- ALWAYS keep a worklog: before ending a session or making a significant commit, write or update
  `docs/worklog/YYYY-MM-DD-<topic>.md` (goal, what changed and why, how it was verified, open items) and add a
  pointer line to it at the top of the list in `docs/worklog/README.md`. Commit the worklog with the work it describes.

## Run & test (Python via uv, not npm)

```bash
# setup: ./scripts/setup.sh   (uv sync -> ./.venv, Playwright Chromium -> ./.playwright-browsers, frontend build, Ollama + qwen3:14b)
# Playwright browsers are project-local; career_agent and tests/conftest.py point PLAYWRIGHT_BROWSERS_PATH at them automatically.
# Never run bare `playwright install` / `npx playwright install` — that writes to ~/Library/Caches (user scope) and the wrong build.
# career_agent — reach → fill an application (dry-run; nothing submitted by default)
PYTHONPATH=src uv run python -m career_agent.apply --url "<job-url>"     # or --job-id <N>
# tests
PYTHONPATH=src uv run python -m pytest tests/career_agent               # add RUN_BROWSER_TESTS=1 for Playwright fixtures
# dashboard — API/service lives in src/job_dashboard/ (api/app.py)
```

## Tests must fail fast

- Tests never wait on real services, models, sleeps or timeouts: no Ollama, no network, no real embeddings, no `time.sleep`. Fake the seam (`tests/conftest.py` already patches `qbank.default_embed` and `local_model.ensure_running/stop` for every test) or inject a fake clock/page.
- A test that needs a missing external dependency must fail or skip immediately, not poll. Per-test timeout is 30s (`pytest-timeout`, `pyproject.toml`); the full suite should stay around a minute. Check with `uv run pytest -q --durations=10` and fix anything over ~2s.
- Never let a test start or kill the developer's Ollama.

## career_agent boundaries

- **Submit is gated by default (dry-run, `do_submit=False`).** It auto-submits only under a **durable, revocable user authorization** — not a per-application tap once granted. This is the path to autonomy.
- **Account creation is handled by `credential_provider.py`.** For new sites it generates a password, saves to `data/secrets/credentials.json`, and completes registration (email → OTP → password → T&C). On repeat visits it loads saved credentials and logs in. Credentials are local-only — never committed, never in model context.
- **Secrets never committed; PII stays local** (local LLM; user-authorized Gmail read for OTP only).
- **One data root, one browser.** Every write goes under `job_dashboard/paths.py` (`data/` or `$JOB_DASHBOARD_DATA_DIR`) — never `~` or `/tmp`. Every browser consumer attaches to the isolated agent Chrome via `job_dashboard/agent_browser.py` — never the user's own Chrome.
- **One LLM client.** Every model call goes through `job_dashboard/llm.py` (OpenAI-compatible Responses API, `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`). Don't call a provider directly.

## Where knowledge lives (query on demand — don't inline)

- **ATS page-handling / archetypes** → `python3 scripts/ats_graph.py query <term>` (human map: `docs/career-agent/ats-knowledge-graph.md`)
- **Question bank** (canonical questions, answered once on the dashboard Answers tab) → `data/jobs.db` tables `qbank_entry`/`qbank_wording`; maintenance `PYTHONPATH=src python3 scripts/qbank.py seed|migrate|calibrate`; spec `docs/superpowers/specs/2026-09-26-question-bank-design.md`
- **Essay ingredient bank + writing style** (one unit per project, for drafting free-text) → `data/answer_style/ingredients.json`
- **Architecture / design** → `docs/career-agent/`

## Agent skills

### Issue tracker

Issues live in GitHub Issues (`Rontor3/job-dashboard`), via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
