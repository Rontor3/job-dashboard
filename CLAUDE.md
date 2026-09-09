# Job Dashboard — Claude Code config

Two coupled subsystems in one repo, sharing `data/jobs.db`:
- **`src/job_dashboard/`** — scrape jobs, match, render résumés, profile store, API/extension (the "front half").
- **`src/career_agent/`** — autonomous job-application form-filler (the "back half"); reuses `job_dashboard`'s profile store, LLM, résumé rendering, and screening.

The dashboard produces jobs + profile; the agent consumes them to apply. This file is a small **index** — query the stores below on demand; don't inline them.

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

## Run & test (Python, not npm)

```bash
# career_agent — reach → fill an application (dry-run; nothing submitted by default)
PYTHONPATH=src python3 -m career_agent.apply --url "<job-url>"     # or --job-id <N>
# tests
PYTHONPATH=src python3 -m pytest tests/career_agent               # add RUN_BROWSER_TESTS=1 for Playwright fixtures
# dashboard — API/service lives in src/job_dashboard/ (api/app.py)
```

## career_agent boundaries

- **Submit is gated by default (dry-run, `do_submit=False`).** It auto-submits only under a **durable, revocable user authorization** — not a per-application tap once granted. This is the path to autonomy.
- **Secrets never committed; PII stays local** (local LLM; user-authorized Gmail read for OTP only).

## Where knowledge lives (query on demand — don't inline)

- **ATS page-handling / archetypes** → `python3 scripts/ats_graph.py query <term>` (human map: `docs/career-agent/ats-knowledge-graph.md`)
- **Learned answers** (recall-first, grows from phone edits) → `data/jobs.db` table `learned_answers`
- **Essay ingredient bank + writing style** (one unit per project, for drafting free-text) → `data/answer_style/ingredients.json`
- **Architecture / design** → `docs/career-agent/`
