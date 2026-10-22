---
name: live-apply-check
description: Live end-to-end check of the career agent — dry-run one application per channel (Indeed, Himalayas, Instahyre, Work at a Startup, Wellfound, a company career site) in the agent Chrome, grade every answer for relevance, class every blank (captcha / needs-you / agent gap), and leave only the final pages plus an HTML report open. Use when asked to "live test", "do live runs", "check the agent on real jobs", or after a batch of agent changes.
---

# Live apply check

Goal of the agent being checked: **everything gets filled except a captcha and knowledge only the candidate has.**
Every blank that is not one of those two is an agent gap to fix.

## Preconditions (check, don't assume)
1. Agent Chrome is up on CDP: `curl -s localhost:9222/json/version`. Never restart or close Chrome, and never close
   a tab that was open before the check (see `src/career_agent/CLAUDE.md`, rule 2026-10-20). If Chrome is down, ask.
2. Local model for answers: `ollama list` answers; if not, `/opt/homebrew/bin/ollama serve &` (or `open -a Ollama`).
3. Know which code is under test (a worktree's `src`) and which data is live (the main repo's `data/jobs.db`).

## Run
From the **main repo root** (live data), PYTHONPATH at the code under test:

```bash
PYTHONPATH="<worktree>/src" python3 "<worktree>/scripts/live_check.py"            # 6 default channels
PYTHONPATH="<worktree>/src" python3 "<worktree>/scripts/live_check.py" --channels indeed,career_site --per 2
PYTHONPATH="<worktree>/src" python3 "<worktree>/scripts/live_check.py" --jobs 31318,31316   # exact jobs
```

Run it in the background and watch the `===` / `---` lines; the last line is `REPORT <path>` and the report tab
opens in the agent Chrome. Logs per job: `data/agent_runs/live_check/<stamp>/<job>.log`; all rows in `results.json`.

What the script guarantees:
- **Dry run only**: `--review` (never the final submit click) + `--park` (never waits on the human).
- **One job at a time.** Picks one untried Strong/Good/Moderate-fit job per channel; skips one-click boards
  (Naukri native, iimjobs, LinkedIn Easy Apply) because their Apply IS the submit.
- **Tabs**: tabs open before the check are never touched; of each job's tabs only its final page is kept.
- **Grading**: Claude haiku grades each (question, answer): 2 relevant / 1 partial / 0 wrong; each blank:
  captcha / needs_you / gap.

## After the run
1. Read the report's header line: answered, % fully relevant, wrong, gaps.
2. For each `⚠️ agent gap` and `❌ wrong`: open that job's log, find the root cause (perception, entry/reach,
   credentials, answer, fill), fix it **generically** (by page structure, never a site name), add a test, commit.
3. Re-run only the affected jobs with `--jobs <ids>` to confirm.
4. Stop the local model when done: `pkill -f "ollama serve"` (and `pkill -f Ollama.app`).
5. Record new findings in memory (`career-agent-live-fixes-*`), one line per root cause.

## Never
- Never submit, never solve a captcha, never enter a password by hand, never close the human's tabs.
- Never "fix" a gap by naming a site; never count a filled site-search/newsletter box as a filled field.
