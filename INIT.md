# INIT — agent playbook for starting this app

You are the agent a user talks to instead of reading the code. Follow this file whenever the user asks to **start,
run, open, set up or reconfigure** the app, or asks what it is doing, which credentials it uses, or which model it
runs. It covers three cases:

1. **First run**: no setup state yet. Run the [onboarding interview](#2-onboarding-interview), write the state file, then start.
2. **Normal start**: setup is done. Run the [preflight](#4-start-the-app), give a 3-line summary of the config, start.
3. **Reconfigure**: the user wants to change one thing. Re-ask only that group, update the state file.

The user's choices live in **`data/setup-state.md`** (gitignored, because everything under `data/` is). This file
(`INIT.md`) is the procedure and gets committed. The state file must never hold secret values, only whether each
one is present.

## 0. Isolation contract (the user's standing rule, which overrides convenience)

- **Inputs are only what the user gives the app explicitly:** the repo `.env`, files under `data/`, and what they
  type into the dashboard or this interview. Never read or reuse credentials from anywhere else: `~/.claude`,
  `~/.aws`, the keychain, the user's own Chrome profile, other repos, or shell variables they didn't put in `.env`.
  If an `LLM_*`, `TELEGRAM_*` or other app variable is set in the shell but not in `.env`, say so and ask before
  relying on it, because the shell takes precedence over `.env`.
- **Every write stays in this directory**: `data/` (or `$JOB_DASHBOARD_DATA_DIR`, which should point inside the
  repo), `.venv/`, `.playwright-browsers/`, `frontend/node_modules`. Nothing goes in `~`, `/tmp` or system caches.
- **Known gaps; tell the user about them, don't hide them:**
  - **Ollama** keeps model weights in `~/.ollama/models` and is installed system-wide (`brew install --cask`). To keep
    weights in the repo, run the server as `OLLAMA_MODELS=$PWD/data/cache/ollama ollama serve` instead of the
    macOS app. Note that `apply/local_model.py` currently starts and stops the *app*. A hosted model (group B)
    avoids Ollama entirely.
  - **uv and npm caches** (`~/.cache/uv`, `~/.npm`) are written during setup. Point them inside the repo with
    `UV_CACHE_DIR=$PWD/data/cache/uv` and `npm_config_cache=$PWD/data/cache/npm` when running `scripts/setup.sh`.
  - **Claude assist** calls the user's own `claude` CLI login and writes its transcripts under `~/.claude`. It is
    **off** unless the user sets `CAREER_AGENT_CLAUDE_ASSIST=1` in `.env` (group H).

## 1. Decide which case you're in

Read `data/setup-state.md` (or `$JOB_DASHBOARD_DATA_DIR/setup-state.md` if that variable is set in the shell or `.env`).

- Missing → first run.
- `status: partial` → resume onboarding at the first group not marked done.
- `status: complete` but `init_version` is lower than **3** (this file's version) → ask only about the groups added
  since that version, then bump `init_version`.
- `status: complete` and current → normal start.

Never assume the state file is accurate. Preflight (section 4) re-checks reality and reports any drift, for
example "state says Gmail is connected but `data/secrets/gmail_token.json` is gone".

## 2. Onboarding interview

Ground rules:

- **One group per turn.** Ask with `AskUserQuestion` when the answer is a choice; use plain text when it is free-form.
  Put the recommended option first and say why in one line.
- **Every group can be skipped.** Say what stops working if they skip it, then move on. Don't ask twice in one session.
- **Never take a secret through chat.** For keys, passwords and tokens, tell the user which line to put in `.env`
  (copy it from `.env.example` if `.env` doesn't exist yet), wait until they say it's done, then check only that the
  key is present: `grep -c '^KEY=.\+' .env`. Never print, echo or log the value. If they paste a secret into chat
  anyway, don't repeat it. Write it to `.env` for them and tell them to rotate it if the chat is shared.
- **Explain before asking.** Each group starts with one sentence on what the item is for and where it ends up.
- After each group, update `data/setup-state.md` with `status: partial`, so a session that dies partway can resume.

Go through the groups in this order. The first three are needed for a useful first session; the rest make the
experience better.

### Group A: Toolchain (check it, don't ask)

Check `uv --version`, `node --version` (18 or newer), that `.venv/` exists, that `frontend/dist/index.html` exists,
and that `.playwright-browsers/` exists. If anything is missing, offer to run `./scripts/setup.sh`. Warn first that
it downloads the default model (about 9 GB) unless group B picks a hosted model, in which case run the steps from
that script by hand and skip the `ollama pull`. Never run a bare `playwright install`.

### Group B: Language model (the most important choice)

**What to tell the user:** one LLM setting drives every model call in both halves of the app: company
classification, fit ranking (verdict, score, strengths, gaps), judging LinkedIn hiring posts, classifying the daily
mail scan, screening answers, essay and cover-letter drafting, and résumé bullet rewrites. All of them go through
`src/job_dashboard/llm.py`, which speaks the OpenAI-compatible **Responses API** (`POST {LLM_BASE_URL}/responses`).

What does **not** use the LLM, so the user knows exactly what changing it affects:

| Task | What actually runs | Configurable? |
|---|---|---|
| Deduplication | Rule-based: normalized company + title (`match/dedup.py`) | No (no model involved) |
| First-pass relevance score | Local embeddings, `Alibaba-NLP/gte-modernbert-base` (`match/embedder.py`), downloaded once into `data/cache/` | Code constant only |
| Question-bank matching | Local ONNX `all-MiniLM-L6-v2` via Chroma | Code constant only |
| Unsticking the apply agent | Headless `claude -p` CLI (see group H) | On/off |

**Default:** local Ollama at `http://localhost:11434/v1` running `qwen3:14b`. It's private, since nothing leaves the
machine, and costs nothing, but it needs about 16 GB of RAM and is slower than a hosted model. Essay quality varies.

Check the machine before recommending anything: `sysctl -n hw.memsize` on macOS, `free -g` on Linux. Then offer:

1. **Keep local `qwen3:14b`** (recommended if RAM is 16 GB or more and privacy matters most).
2. **A smaller local model** (recommended if RAM is under 16 GB). Set `LLM_MODEL` and `OLLAMA_MODEL` to the tag and
   `ollama pull` it. Warn that ranking and essays get noticeably worse.
3. **Hosted OpenAI**: `LLM_BASE_URL=https://api.openai.com/v1`, `LLM_API_KEY`, `LLM_MODEL=gpt-5-mini`. Reasoning
   models also need `LLM_NO_TEMPERATURE=1`. This is the best quality for essays and ranking, and the queue no longer
   starts or stops Ollama.
4. **A custom endpoint** (OpenRouter, vLLM, LM Studio, a company gateway): set the same three variables. The endpoint
   **must implement `/responses`**; plain `/chat/completions` won't work.

If they pick 3 or 4, **say plainly what leaves the machine**: their profile and résumé text, job descriptions,
application questions and drafted answers go to that provider. Ask them to confirm.

Optional knobs to mention only if relevant: `LLM_REASONING_EFFORT` (none, low, medium or high; defaults to `none` on
local Ollama) and `LLM_TIMEOUT` (180 seconds). For local Ollama, recommend raising the context length
(`OLLAMA_CONTEXT_LENGTH=16384` or the Ollama app's settings), because hiring-post judging sends a résumé-sized prompt.

**Verify** with a real call, without printing the key:

```bash
PYTHONPATH=src uv run python -c "from job_dashboard import llm; c=llm.config(); print(c.base_url, c.model); print(llm.complete('Reply with exactly: OK'))"
```

### Group C: Who you are (required for ranking and applying)

Each item says where it's stored and what reads it. Check each one and ask only for what's missing.

| Item | Stored in | Used by | If missing |
|---|---|---|---|
| Candidate profile (experience, skills, goals) | `.claude/skills/ai-job-search/skills/job-application-assistant/01-candidate-profile.local.md` | embedding score and LLM ranking | ranking runs against a placeholder, so scores are meaningless |
| Current résumé PDF | `data/current_resume.pdf` (or `CURRENT_RESUME_PDF`) | hiring-post judging, profile text, uploads | hiring view can't score; uploads fail |
| Application profile (name, email, phone, location, links, work authorization, notice period, salary, CTC) | `application_profile` table in `data/jobs.db`; edit it in the dashboard's Apply panel or with `PUT /api/application-profile` | form filling, eligibility flags | the agent can't fill basic fields |
| **Account-creation identity**: `CAREER_AGENT_EMAIL`, `CAREER_AGENT_FIRST_NAME`, `CAREER_AGENT_LAST_NAME` | `.env` | registering new ATS accounts (`browser/credential_provider.py`) | ⚠ **First and last name fall back to a hard-coded placeholder person and the email to empty.** Treat these as required before any apply run. |
| Résumé LaTeX contact and education | `src/job_dashboard/resume_segments/*.local.tex` | rendered résumé PDFs | PDFs carry placeholder contact details |
| Essay ingredients and writing style | `data/answer_style/ingredients.json` | long free-text answers | essays come out generic |

Offer to draft `01-candidate-profile.local.md` from their résumé PDF if they have one. Don't invent facts. Ask about
anything you can't ground in the résumé.

### Group D: Gmail (optional, strongly recommended for applying)

Explain the three uses separately, because they need different permissions:

- **Read-only** (`gmail.readonly`, token `data/secrets/gmail_token*.json`):
  - reads OTP codes and verification links during sign-ups;
  - runs the **daily mail scan** that moves tracker cards to interview, rejected or selected;
  - optionally checks for "application received" emails as proof of a submit (setting `gmail_confirmation_check`,
    off by default, subject lines only).
- **Compose** (`gmail.compose`, token `data/secrets/gmail_compose_token.json`): creates outreach drafts in the
  hiring view. Drafts only; nothing is ever sent.

Setup: the user makes an OAuth *Desktop* client in Google Cloud Console and saves it as
`data/secrets/gmail_credentials.json`. Then they run these themselves, because each opens a browser consent page:

```bash
PYTHONPATH=src uv run python -m career_agent.integrations.gmail_otp authorize
```

```bash
PYTHONPATH=src uv run python -m job_dashboard.apply.gmail_draft authorize
```

Never click through the consent screen for them. If they skip this group: sign-ups that need an OTP stop and park,
the tracker doesn't update from email, and outreach falls back to a pre-filled Gmail compose link.

### Group E: Job sources and site logins (optional)

The no-login sources (Indeed and LinkedIn via jobspy, Himalayas, RemoteOK, Remotive, WeWorkRemotely) run on every
Refresh with no setup. The logged-in sources are **off by default**. Each one is a dashboard setting:
`browser_linkedin_enabled`, `_naukri_`, `_wellfound_`, `_instahyre_`, `_iimjobs_`, `_indeed_` and `_ycstartups_`.

For each site the user wants, the agent's own Chrome opens (its profile is at `data/browser/profile`, debug port
9333, separate from the user's everyday Chrome). **The user logs in there once, by hand.** Cookies stay in that
profile. Don't type their passwords.

Naukri also has an API session: `NAUKRI_USERNAME` and `NAUKRI_PASSWORD` in `.env`, then the user runs
`python3 scripts/naukri_login.py` (it may prompt for an OTP). That writes `data/secrets/naukri_session.json`. The
session is tied to their IP and expires, so it needs redoing occasionally.

### Group F: Phone hand-off (optional)

- **Telegram** (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` in `.env`; create the bot with @BotFather and get the chat id
  from @userinfobot): during apply runs the agent asks unanswered questions and Submit/Skip approvals on Telegram.
  The queue waits `telegram_wait_minutes` (10 by default) and then parks the job. Without Telegram, queued jobs
  park straight away for review in the dashboard.
- **Tailscale** (optional, `TAILSCALE_HOST` or auto-detected): a live view of the agent's browser on the user's
  phone, for solving captchas remotely. It only binds to the tailnet interface.

### Group G: Extras (optional)

- **TinyFish** (`TINYFISH_API_KEY`): company research for cover letters. Without it, letters use a general template.
- **LaTeX** (`lualatex` from MacTeX or TeX Live): needed only to render résumé and cover-letter PDFs.

### Group H: Autonomy and safety defaults (confirm, don't skip)

Read these back and ask whether to keep them. The defaults are conservative on purpose.

| Setting | Default | Meaning |
|---|---|---|
| Auto-submit per board (`autosubmit_naukri`, `_linkedin`, `_indeed`, `_iimjobs`, `_instahyre`, `_wellfound`, `_workatastartup`, `_career_site`) | all **off** | without it the agent fills the form and stops before Submit (dry run) |
| Graduated autonomy | an answer needs **3** untouched approvals; the first submit on any new kind of site always goes through you | applies even when auto-submit is on |
| `autosubmit_daily_cap` | 5 a day | most automatic submits in any 24 hours |
| Rate limits (`RATE_LIMIT_DOMAIN_DAY`, `RATE_LIMIT_HOUR`, `RATE_LIMIT_PACE`) | 5 per domain per day, 10 an hour, `medium` | how often the agent may hit a site |
| Claude assist (`CAREER_AGENT_CLAUDE_ASSIST=1` in `.env`) | **off** | when the agent is stuck, a headless `claude -p` gets a **screenshot of the page** and the list of clickable controls, and picks one click (5 calls per run at most). It can never type, submit, log in or touch captchas. It uses the user's **own Claude login** and sends the screenshot to Anthropic, so ask explicitly; don't nudge. |
| Generated ATS passwords | random, saved to `data/secrets/credentials.json` | the agent creates and reuses site accounts; the passwords never enter any model's context |

## 3. Write `data/setup-state.md`

Write exactly this shape. Put choices and presence flags in it, never secret values.

```markdown
---
status: complete            # partial while onboarding is in progress
init_version: 3
updated: YYYY-MM-DD
---
# Setup state (written by the agent from INIT.md; safe to edit by hand)

## Model
- provider: local-ollama | openai | custom
- base_url: http://localhost:11434/v1
- model: qwen3:14b
- data leaves machine: no
- verified: YYYY-MM-DD

## Identity
- candidate profile .local.md: yes/no
- current_resume.pdf: yes/no
- application profile complete: yes/no (missing: ...)
- CAREER_AGENT_EMAIL / FIRST_NAME / LAST_NAME set: yes/no

## Integrations
- gmail read-only: connected/skipped     - gmail compose: connected/skipped
- browser sources enabled: [linkedin, ...] - naukri api session: yes/no
- telegram: yes/skipped    - tailscale: yes/skipped
- tinyfish: yes/skipped    - latex: yes/no

## Autonomy
- auto-submit boards: none
- daily cap: 5   - claude assist: off

## Skipped, nudge later
- <item>: <what it would unlock>
```

The "Skipped, nudge later" list is how you nudge gently: on later starts, mention **at most one** skipped item that
would help with what the user is doing right now. Mention each item no more than once a week. Store the date next
to the item.

## 4. Start the app

Preflight, then report in three lines or fewer, for example:
`Model: qwen3:14b (local) ✓ · Profile ✓ · Gmail ✗ (OTP sign-ups will park) · Auto-submit: off`.

1. If the LLM is local Ollama, check it's up (`curl -fs -m 2 localhost:11434/api/version`). If it isn't, ask before
   starting it.
2. Re-check the presence flags from the state file and report drift.
3. Start the server **and the agent window** with one command:

   ```bash
   PYTHONPATH=src uv run python -m job_dashboard.start
   ```

   This serves the dashboard on port 8000, then opens it as a tab in the agent's own Chrome (port 9333, profile
   `data/browser/profile`). If that Chrome is already running, it focuses the existing dashboard tab instead of
   opening another. In the Claude desktop app, `preview_start` with name `dashboard` runs the same launcher.
   `--no-browser` serves without opening anything; `--port N` changes the port.

**One window.** That Chrome window is the entire app. The dashboard is one tab. Every agent run (filling a form,
reading a LinkedIn post, scraping a logged-in board) opens as **another tab in the same window**, and an apply run
brings its tab to the front so the user can watch it work and take over. Job links from the dashboard open there
too. Tell the user not to open the dashboard in their everyday browser, because the agent's logins and tabs live
only in this window. This doesn't work with `CAREER_AGENT_CDP_URL=off`, which makes runs use a separate Playwright
Chromium.

## 5. What runs in the background (tell the user on first start)

As soon as the server starts:

- **Loads `.env`** from the repo root. Variables already set in the shell take precedence.
- **Embedding model load** on a background thread. The first time, it downloads into `data/cache/`.
- **Submit watcher** thread: every 30 seconds it looks at the agent Chrome for forms parked for review and notices
  when you submit one by hand. It only reads the page; it never clicks. It also checks Gmail subjects if
  `gmail_confirmation_check` is on.
- **Daily mail scan** thread: checks every 30 minutes and scans once a day, provided Gmail read-only is connected.
  The first scan looks back 30 days. It moves tracker cards and uses the LLM to classify messages.

Only when the user triggers it:

- **Refresh**: scrape, then dedupe, then classify companies (LLM), then score embeddings.
  Deep ranking (`scripts/deep_rank.py` or the `/rank` skill) is a separate step.
- **Apply or the queue**: runs `career_agent.apply` as a subprocess, one at a time, and launches the agent Chrome on
  port 9333 if it isn't running. **On macOS with local Ollama, the queue opens Ollama when it starts and quits it
  (`pkill -f Ollama.app`) when the queue finishes, if the queue was the one that started it.**
- **Hiring refresh**: reads LinkedIn posts through the agent Chrome and scores them with the LLM.

All files the app writes go under `data/` (or `$JOB_DASHBOARD_DATA_DIR`). Secrets are in `data/secrets/` and
site logins in `data/browser/profile/`. To back up, copy that one folder.

## 6. Where a credential comes from (quick reference)

| The user asks "where does X come from?" | Answer |
|---|---|
| LLM key and endpoint | `.env` → `LLM_*`, read by `src/job_dashboard/llm.py` |
| Name, email and phone typed into forms | `application_profile` in `data/jobs.db` (dashboard Apply panel) |
| Name and email on new ATS accounts | `.env` → `CAREER_AGENT_EMAIL`, `_FIRST_NAME`, `_LAST_NAME` |
| ATS account passwords | generated by the agent, stored in `data/secrets/credentials.json` |
| LinkedIn, Naukri and other site logins | cookies in the agent's Chrome profile `data/browser/profile/`, from the user's one-time manual login |
| Naukri API session | `scripts/naukri_login.py` → `data/secrets/naukri_session.json` |
| Gmail access | OAuth tokens in `data/secrets/gmail_token*.json` (read) and `gmail_compose_token.json` (drafts) |
| Telegram, TinyFish | `.env` |
