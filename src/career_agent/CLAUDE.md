# career_agent — Claude Code config

Autonomous job-application filler. Consumes profile + jobs from `job_dashboard`; drives Playwright to fill and submit ATS forms.

## Run

```bash
# Dry-run (default — never submits)
PYTHONPATH=src python3 -m career_agent.apply --url "<job-url>"
PYTHONPATH=src python3 -m career_agent.apply --job-id <N>

# Submit (still human-gated)
PYTHONPATH=src python3 -m career_agent.apply --url "<url>" --submit

# Escape hatches
--no-langgraph   # skip graph, run plain walk()
--no-llm         # skip judgment tier, rules + memory only
--no-telegram    # CLI approver instead of Telegram
--cdp-url URL    # attach to existing Chrome (overrides CAREER_AGENT_CDP_URL in .env)

# Tests
PYTHONPATH=src python3 -m pytest tests/career_agent
```

## CDP browser (real Chrome, real sessions)

The agent uses an existing Chrome instance via CDP instead of launching headless Playwright.
Set once in `.env`:
```
CAREER_AGENT_CDP_URL=http://localhost:9222
```

Launch the career agent Chrome (Profile 3, `rakshitagent@gmail.com`) before running:
```bash
pkill -x "Google Chrome" 2>/dev/null; sleep 2; \
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.career_agent/chrome-p3" \
  --profile-directory="Profile 3" \
  --no-first-run --no-default-browser-check &
```

Profile data lives at `~/.career_agent/chrome-p3/Profile 3` (symlink → real Chrome Profile 3).
Sessions persist there — log in to job sites once in that Chrome window; future runs are authenticated.
If Chrome isn't running, `launch()` falls back to `launch_persistent_context` automatically.

## Execution path

```
apply.py
  ├── [default] _run_graph() → LangGraph (orchestrator/graph.py)
  │     classify → cred_provide? → reach → perceive → fill → human_gate? → advance → loop
  │     exception → falls back to walk()
  └── [--no-langgraph] walk() → step_engine.py
```

## fill_node answer ladder

1. **FTS5 recall** — `learned_answers` table (jobs.db) — exact/keyword match
2. **Semantic match** — ChromaDB `behavioral_qa` — vector match; confidence ≥ 1.0 → autonomous (no human gate)
3. **Rule-based mapper** — `orchestrator/screen_review.py` — standard_answers + profile_resolver
4. **LLM judgment** — qwen3:14b local / Claude Pro (cap 6/app) — novel free-text fields
5. **Human gate** — Telegram collector → `interrupt()` → `Command(resume=answers)`

## Tri-Partite Memory (`memory/` + `routers/memory_router.py`)

| Op | Vault | Rule |
|----|-------|------|
| `GET_PROFILE_CHUNK(section)` | `factual_core.py` — static profile JSON | — |
| `EXACT_TECH_SEARCH(keywords)` | `exact_tech.py` — FTS5 over `ingredients.json` | Return `source` verbatim. NEVER paraphrase. |
| `SEMANTIC_MATCH(question)` | `semantic_behavior.py` — ChromaDB ONNX | confidence ≥ 1.0 = autonomous |
| `RECORD_FEEDBACK(q, a, event)` | semantic + FTS5 dual-write | event = `"approve"` or `"edit"` |

Confidence: 0.0 → +1/3 per approve → 1.0 after 3 = AUTONOMOUS. Edit resets to 0.0.

## Data paths

| What | Where |
|------|-------|
| SQLite (jobs, learned_answers, profile) | `data/jobs.db` |
| Semantic vectors | `data/semantic_behavior/` |
| Ingredient bank | `data/answer_style/ingredients.json` |
| LangGraph checkpoints | `data/jobs_graph.db` |

## Session start: check pending memory updates

`data/pending_memory_updates.md` is written by `apply.py` after every run.
**At the start of any session, check if this file exists and has unreviewed entries.**
For each run entry:
- Escalated fields with a known purpose → add standing answer to `career-agent-user-answers.md`, wire into code
- New ATS behaviour (unexpected stop, new gate, layout quirk) → add to `career-agent-phase3b-findings.md`
- After promoting all entries, clear the file (truncate to empty)

```bash
cat data/pending_memory_updates.md
```

## Maintenance: when answers change

**After any live session that hits a new ATS field type:**
1. Add findings to memory file `career-agent-phase3b-findings.md`
2. If a new field was escalated that should be auto-filled, add it to this checklist

**When `career-agent-user-answers.md` gets new values, verify code matches:**

| New value type | Where to wire it |
|---------------|-----------------|
| New standard Yes/No answer (e.g. COI) | `form_model.py` → KNOWN_PURPOSES + _RULES rule; `standard_answers.py` → answer(); `screen_review.py` → _STD_PURPOSES |
| New demographic value | `profile.contact` in DB already has the key; `profile_resolver.py` → _DEMO mapping; verify `_coerce_option` can match the EEO option text |
| New profile text field (salary, location) | `form_model.py` → _RULES rule; `profile_resolver.py` falls through to `profile.contact.get(purpose)` — just add the rule |
| New attestation policy change | `screen_review.py` → map_screen() attestation branch |

Quick check to run after any wiring:
```bash
PYTHONPATH=src python3 -m pytest tests/career_agent/ -q
```

## Hard rules (never negotiate)

- **Submit is human-gated.** `do_submit=False` by default. Auto-submit only under `--autonomous`.
- **Captcha = detect + escalate only.** Remote-solve via Tailscale live-view (human solves on phone). Never solve programmatically.
- **Account creation is automated but credential-gated.** `credential_provider.py` generates a password, saves it to `~/.career_agent/credentials.json`, and registers the account (Darwinbox: email→OTP→password→T&C→sign-up). On repeat visits it loads the saved credential and logs in. Credentials are local-only — never committed, never in model context.
- **No PII committed.** Profile JSON lives outside repo. Secrets in `.env` / env vars only.
- **Exact Tech source is verbatim.** Never paraphrase or summarise `ingredients.json` source fields.

## Module map

```
apply.py                  — CLI entrypoint; builds MemoryRouter; runs graph or walk
orchestrator/
  graph.py                — LangGraph StateGraph + all 7 nodes
  step_engine.py          — plain-Python walk() fallback
  screen_review.py        — map_screen() rule-based mapper
  judgment.py             — LLM judgment tier
  advance.py              — Next/Submit click logic
  mapper.py               — FillDecision dataclass + field→value logic
  profile_resolver.py     — maps purpose → profile value
browser/
  perception.py           — A11y-tree → Field list
  page_prep.py            — classify_entry, enter_application, prepare
  gate_probe.py           — captcha/gate detection
  credential_provider.py  — email/password fill for existing accounts
  form_model.py           — Field dataclass
memory/
  factual_core.py         — load_profile, get_profile_chunk
  exact_tech.py           — ExactTechVault (FTS5, verbatim source)
  semantic_behavior.py    — SemanticBehaviorVault (ChromaDB ONNX)
  learned_answers.py      — AnswerMemory (FTS5 fast-path, jobs.db)
routers/
  memory_router.py        — MemoryRouter, memory_access() dispatcher
integrations/
  telegram/collector.py   — field prompts; JD context on company-Q labels
  telegram/approver.py    — submit/skip gate
  live_view/session.py    — CDP screencast for remote captcha solve
```
