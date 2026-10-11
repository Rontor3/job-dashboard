# Agent-driven apply runs: the in-app agent owns each application

Date: 2026-10-11 · Status: approved by user in chat (grilling session) · ADR: `docs/adr/0002-agent-owns-apply-runs.md`
Builds on: `2026-10-10-in-app-agent-design.md`, `2026-09-26-question-bank-design.md`

## Problem
Today `career_agent` fills forms with a script:
- The LangGraph walk or a board loop moves through the pages.
- A ladder picks the values: question bank → profile rules → LLM judge.
- Whatever is left is escalated to the user.

The in-app agent sees a run only after it has stopped (Inbox, `list_needs_you`). That causes two problems:
- **Dead ends are terminal.** When the script meets something it can't handle (an odd control, a new question, a field that fails validation), nobody can reason about it in the moment.
- **Draft answers look like real ones.** The user can't tell an answer the model composed from one they gave earlier.

## Goal
The in-app agent drives every application through tools, with the app as its harness. The parts:
- **A DOM-first form view.** The agent reads the structured field list, not screenshots.
- **The split of work.** The agent decides values; a script fills them and checks the result; anything that fails goes back to the agent.
- **Grounding.** Every answer is grounded in a stored source and carries a citation. Anything else is visibly marked as written by the agent.
- **Priority.** The user's priority for the job decides whether those agent-written answers block submit.
- **Pausing.** When the agent can't answer, the run pauses with the tab still open and a clear status, and the queue moves on.

Get it working first; optimise later.

## Decisions

### Who drives
- **The agent owns the run.** It calls tools for every step: open the job, reach the form, snapshot the form, fill, verify, advance, submit, and pause or skip. Existing Python code becomes those tools, with no duplicate engine. The script engine stays as the default (`apply_engine=script`) until this one is verified.
- **Model:** the configured `LLM_*` model, through `pi-ai` (ADR 0001).

### Perception: DOM first
- `apply_snapshot` returns the current page's fields as compact JSON: short ids (`f3`), label, kind, required, current value, invalid flag, and up to 20 options plus a count of the rest.
  - Each field carries a **suggestion** from the existing ladder (`answering.answer_fields` without the LLM judge), with its source and citation. The agent mostly confirms or overrides.
  - Board pages use the board driver's field list (LinkedIn's Easy Apply modal lives in shadow DOM). Career sites use `perception.snapshot_form`.
  - Sensitive fields (bank or government ID) are listed separately and can never be filled.
- `apply_page_text` and `apply_screenshot` are fallbacks. The screenshot reports "unsupported" when the model takes no images.

### Fill → verify → back to the agent
- `apply_fill(answers[{ref, value, source, citation?}])`:
  - The server rejects sensitive fields.
  - It requires a citation for every source except `agent`.
  - It maps each value onto the field's real options.
  - It fills, revalidates and reads the values back.
  - It returns `{applied, mismatched, required_empty, invalid, new_fields}`, and the agent handles each failure.
- **Confidence = grounding.** An answer counts as confident when it comes from, and cites, one of these:
  - the application profile;
  - the question bank;
  - the résumé;
  - the essay ingredients (verbatim);
  - the job description;
  - an option that maps to one of these.

  `apply_lookup(question)` returns those candidates. Anything the agent composes is `source=agent`, saved with `agent_written=1`, and shown to the user as **"written by the agent, not your words"**.

### Priority
- `jobs.priority`: `low | normal | high | dream` (default from the `apply_priority_default` setting, `normal`). It is set on the job or queue row, or by the agent (`set_job_priority`, with Undo).
- `apply_hold_priorities` (default `high,dream`): at these levels, any agent-written answer **holds submit for the user's review**, even with auto-submit on. At the other levels the form submits with those answers marked.

### Submit
- The agent gets `apply_submit`. The server gates it with the durable authorization in `autonomy.autosubmit_policy`: the per-board switch, grounded sources, the daily cap, and first-submit-per-site. It adds the priority hold on top. Auto-submit is never on by default.
- A held submit is never retried. The agent pauses with reason `review`.
- A submit counts only once the board's own signal (`signals.confirmed`) or the site's confirmation is seen.
- The playbook rule "the agent has no submit tool" is replaced by this gated tool.

### Can't answer → notify → pause
- The agent fills everything it can, then calls `apply_pause(reason, questions[])`:
  - the run state becomes `paused`;
  - the questions are written as `needs_answer`;
  - an Inbox card (`parked_live`) shows **status, what is missing and why**, and Telegram is pinged if it's configured;
  - **the tab stays open** and the queue goes on to the next job.
- At most 5 paused tabs stay open. The 6th closes the oldest, which on resume starts on a fresh page and refills from saved answers (`_prior_human_answers`).
- Inbox actions: **Resume** (UI-only), **Show tab**, **Open run** (the agent session), **Skip**. Answering the last open question re-queues the job, as today. Resume continues on the same tab when it's still alive.

### Walls the agent never crosses
- **Captcha:** detected (`gate_probe`), never solved by code or by the agent. The run skips with reason `captcha`.
- **Sign-up wall** with no saved credential: skip with `account_needed`. `credential_provider` registration is off in agent mode.
- **Sensitive fields:** left blank if optional; if required, the run pauses `sensitive_field`.

### Skills
- Skills are `docs/agent/skills/<name>.md`, with frontmatter `name, description, boards?`. User overrides go in `data/agent/skills/`.
- The system prompt lists their names and descriptions. `load_skill(name)` returns the body plus that board's notes from `ats-graph.json`.
- First skills: `apply`, `linkedin`, `wellfound`, `himalayas`, `shortlist`.
- The new profile `applier` limits each run's session to the apply tools plus a few read tools.

### Queue handoff
- With `apply_engine=agent`, the queue runner starts a background agent session per job (`POST /agent/runs`, the same pattern as the council's child sessions).
- It polls the run state until the run reaches `submitted | paused | skipped | failed`, or 25 minutes pass.
- `announce` gets the new reasons.

## Data
- `jobs.priority TEXT DEFAULT 'normal'`.
- `application_qa` gets `agent_written INTEGER DEFAULT 0` and `citation TEXT` (JSON).
- New table `apply_run`: `job_id` PK, `run_key`, `agent_session`, `state`, `reason`, `detail`, `url`, `tab_target_id`, `tab_open`, `step`, `priority`, `paused_at`, `updated_at`.
- New settings:
  - `apply_engine`, `apply_priority_default`, `apply_hold_priorities`;
  - `autosubmit_skip_first_site` (verification only, reverted afterwards).

## Verification (approved by the user for this rollout only)
Done when there are **3 confirmed submitted applications each on LinkedIn (Easy Apply or external), Wellfound and Himalayas**:
- Auto-submit is on for those boards and `autosubmit_skip_first_site=1` during verification. Both are reverted afterwards.
- The agent shortlists eligible India / remote-India jobs and posts the shortlist to the Inbox (the user can veto). It starts without waiting.
- Captcha, account-needed and location-ineligible listings are skipped with a reason, and the next listing is tried.

## Out of scope
- The agent editing the frontend or UX (next sprint).
- Efficiency work.
- Solving captchas, ever.
