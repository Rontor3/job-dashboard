# Career Agent

Autonomous job-application filler. Given a job URL, it navigates to the ATS, fills the form using your profile, handles multi-step wizards, and stops at a dry-run gate before submitting — or submits when you authorize it.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11 | `python3 --version` |
| Playwright + Chromium | Installed via pip + `playwright install chromium` |
| Google Chrome (real browser) | For CDP mode — Profile 3 is the agent's browser identity |
| Ollama + `qwen3:14b` | For judgment-tier free-text answers. `ollama pull qwen3:14b` |
| Tailscale (optional) | For remote captcha solve — phone + Mac on same tailnet |
| Telegram bot (optional) | For field escalations + submit approval on your phone |

---

## First-time setup

### 1. Install Python dependencies

```bash
cd "path/to/Job Dashboard"
python3 -m venv .jd_env
source .jd_env/bin/activate
pip install -e .
pip install playwright langgraph langgraph-checkpoint-sqlite aiohttp chromadb
playwright install chromium
```

### 2. Create a `.env` file

Copy the template below to `.env` in the project root and fill in your values:

```bash
# Browser — use an existing Chrome with remote debugging (recommended)
CAREER_AGENT_CDP_URL=http://localhost:9222

# Telegram — get token from @BotFather, chat_id from @userinfobot (your personal id)
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Remote captcha solve (Tailscale)
TAILSCALE_HOST=100.x.x.x    # your Mac's Tailscale IP

# LLM (judgment tier)
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen3:14b

# Optional overrides
# CAREER_AGENT_HEADED=true       # show browser window (default: true)
# REMOTE_SOLVE_PORT=8765
# REMOTE_SOLVE_TTL=300
```

### 3. Launch the agent Chrome window

The agent uses Chrome Profile 3 (a dedicated identity separate from your main Chrome). Launch it once before running:

```bash
pkill -x "Google Chrome" 2>/dev/null; sleep 2
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.career_agent/chrome-p3" \
  --profile-directory="Profile 3" \
  --no-first-run --no-default-browser-check &
```

Keep this window open while running the agent. Log in to job sites once here — sessions persist across runs.

### 4. Set up your profile

The agent reads your profile from `data/jobs.db` (the main dashboard database). Make sure you have run the job dashboard at least once and filled in your `application_profile`. Key fields:

- Name, email, phone, address
- LinkedIn URL, work authorization status, visa sponsorship
- Demographic answers (EEOC)

Also populate your résumé in the dashboard under `Rakshit_Singh_draft1` (or pass `--resume-pdf` at runtime).

### 5. Set up Telegram (for interactive runs)

Without Telegram the agent falls back to stdin prompts (CLI mode). With it, unknown fields and submit decisions appear as Telegram messages you answer from your phone.

1. Create a bot via [@BotFather](https://t.me/BotFather) → get `TELEGRAM_BOT_TOKEN`
2. Start the bot, then get your chat id from [@userinfobot](https://t.me/userinfobot) → `TELEGRAM_CHAT_ID`
3. Add both to `.env`

---

## Running the agent

```bash
# Dry-run (default — fills form but never submits)
PYTHONPATH=src python3 -m career_agent.apply --url "https://jobs.example.com/..."

# Use a specific job from the dashboard db (grounds LLM answers in the JD)
PYTHONPATH=src python3 -m career_agent.apply --job-id 123

# Submit (still human-gated — you approve via Telegram or CLI)
PYTHONPATH=src python3 -m career_agent.apply --url "..." --submit

# Attach a specific résumé PDF
PYTHONPATH=src python3 -m career_agent.apply --url "..." --resume-pdf data/resumes/resume.pdf

# Skip LLM (fast dry-run, rules only)
PYTHONPATH=src python3 -m career_agent.apply --url "..." --no-llm

# Skip Telegram (stdin prompts instead)
PYTHONPATH=src python3 -m career_agent.apply --url "..." --no-telegram

# Fall back to legacy walk() instead of LangGraph
PYTHONPATH=src python3 -m career_agent.apply --url "..." --no-langgraph

# Attach to a running Chrome instead of launching a new one
PYTHONPATH=src python3 -m career_agent.apply --url "..." --cdp-url http://localhost:9222
```

**`stopped_reason: reached_submit_dry_run`** = success. The form was fully filled and the agent reached the submit button in dry-run mode.

### Bulk runs

```bash
python3 scripts/run_bulk_applications.py --input urls.txt
```

Results log to `data/bulk_run_log.json`. Each job gets a 15-minute deadline.

---

## How it works

```
apply.py
  ├── LangGraph graph (default)
  │     classify → [cred_provide?] → reach → perceive → fill → [human_gate?] → advance → loop
  └── walk() fallback (--no-langgraph)
```

**Execution path per application:**

1. **classify** — is the page a closed posting / direct form / JD-with-Apply?
2. **reach** — drill from the JD to the real form, following Apply buttons. If a login/password wall appears, routes to `cred_provide` first (one time per run).
3. **perceive** — extract the accessibility tree into a compact Field list
4. **fill** — answer each field via the answer ladder (memory recall → rules → LLM → human gate)
5. **advance** — click Next / Submit; repeat until all pages done
6. **human_gate** — unknown fields or the final submit are held here for your approval via Telegram

**Answer ladder (fill order):**

1. FTS5 recall from `learned_answers` (exact/keyword match on prior approved answers)
2. Semantic match via ChromaDB (`behavioral_qa`) — confident answers (score ≥ 1.0) go autonomous
3. Rule-based mapper (`screen_review.py`) — standard Yes/No, EEOC, contact fields
4. LLM judgment — `qwen3:14b` local; Claude Pro for high-stakes novel fields (capped 4/app)
5. Human gate — Telegram prompt → you type the answer → agent resumes

**Captcha handling:** the agent detects captchas (`gate_probe.py`) and escalates via a Tailscale live-view link sent to Telegram. You solve it on your phone; the agent detects the token and continues. The agent never solves captchas programmatically.

---

## File map

```
apply.py                  CLI entrypoint; builds deps; runs graph or walk
run.py                    Thin runner used by bulk scripts

browser/
  perception.py           A11y-tree → Field list (shadow DOM aware)
  page_prep.py            classify_entry, reach_application_form, consent dismissal
  gate_probe.py           Captcha/gate detection (never solving)
  filler.py               Fill loop; shadow-DOM fill JS
  form_model.py           Field dataclass + purpose rules (_RULES, KNOWN_PURPOSES)
  credential_provider.py  Login/register automation for account walls
                          (Darwinbox, Infosys, SmartRecruiters non-OC)
  ats_lookup.py           Query ats-graph.json for ATS-specific handling notes
  runner.py               Playwright launch / CDP attach helpers

orchestrator/
  graph.py                LangGraph StateGraph — 7 nodes, conditional edges
  step_engine.py          Legacy walk() loop (--no-langgraph fallback)
  screen_review.py        Rule-based map_screen(); standard_answers resolver
  judgment.py             LLM judgment tier (qwen3 + Claude fallback)
  advance.py              Next/Submit click logic; wizard step detection
  profile_resolver.py     Maps field purpose → profile value
  standard_answers.py     Canonical Yes/No answers for EEOC / work auth / etc.

memory/
  factual_core.py         Static profile JSON loader; get_profile_chunk()
  exact_tech.py           ExactTechVault — FTS5 over ingredients.json (verbatim source)
  semantic_behavior.py    SemanticBehaviorVault — ChromaDB ONNX; graduated autonomy
  learned_answers.py      AnswerMemory — FTS5 fast-path over jobs.db learned_answers
  candidate_profile.py    CandidateProfile from résumé segments

routers/
  memory_router.py        MemoryRouter; dispatches GET_PROFILE_CHUNK / EXACT_TECH_SEARCH
                          / SEMANTIC_MATCH / RECORD_FEEDBACK

mcp_server.py             FastMCP server — the 'doing' boundary.
                          Exposes 3 tools: browser_action / memory_access / human_loop_call.
                          apply.py registers the live session via set_session().
                          Run standalone: python -m career_agent.mcp_server

integrations/
  telegram/collector.py   Field prompts to Telegram; escalated-field prompts
  telegram/approver.py    Submit / skip gate via Telegram inline buttons
  live_view/session.py    CDP screencast server for remote captcha solve
  human_loop.py           HumanLoop: ties together collector + approver + remote_solve
  approver.py             CliApprover / CliCollector fallbacks (no Telegram)

config/
  settings.py             All env-var settings; loads .env automatically
```

---

## Key data files

| Path | Contents |
|---|---|
| `data/jobs.db` | SQLite: jobs, application_profile, learned_answers, LangGraph checkpoints |
| `data/semantic_behavior/` | ChromaDB vectors for behavioral answers |
| `data/answer_style/ingredients.json` | Essay ingredient bank (verbatim source; never paraphrase) |
| `data/bulk_run_log.json` | Per-job run results from bulk runs |
| `data/pending_memory_updates.md` | Written after each run; review at session start |
| `~/.career_agent/credentials.json` | Account credentials for ATS account walls (local only) |
| `docs/career-agent/ats-knowledge-graph.md` | Map of ATS page archetypes → tells → strategies |

---

## Safety rules (never change these)

- **Submit is always dry-run by default.** Pass `--submit` to enable; even then, human approval is required unless `--autonomous`.
- **Captchas are never solved programmatically.** The agent detects and escalates only.
- **Account creation is automated but credential-local.** Passwords are generated and saved to `~/.career_agent/credentials.json` only — never committed, never sent to any model.
- **PII stays local.** Profile JSON lives in `data/jobs.db` (not in the repo). Résumés are rendered locally. Secrets in `.env` only.

---

## Tests

```bash
PYTHONPATH=src python3 -m pytest tests/career_agent -q

# With live browser tests (requires Chrome + CDP running)
RUN_BROWSER_TESTS=1 PYTHONPATH=src python3 -m pytest tests/career_agent -q
```
