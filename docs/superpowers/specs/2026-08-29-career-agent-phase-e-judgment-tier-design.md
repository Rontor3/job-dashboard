# Career Agent — Phase E: Judgment Tier (Design)

**Status:** Approved 2026-08-29
**Branch:** `career-agent-phase-e` (off `career-agent-phase3b`)
**Depends on:** Phase 3B (`map_screen`, `profile_resolver`, `standard_answers`, `CandidateProfile`) + the walk (`step_engine`, `apply.py`).

## Motivation

Live runs (JPMC Oracle, Greenhouse, Ashby) proved the *pipeline* — reach, traverse, and fill a real enterprise ATS — but exposed an **answer-quality** gap. The rule-based filler nails structured fields (name, phone, country, city, résumé) and correctly escalates the rest, but it has **no answer** for:

- **Free-text fit/motivation questions:** "Why do you want this role?", "What AI tools have you used?" — currently escalated (blank).
- **Option/enum questions needing semantic mapping:** "Highest level of education" (dropdown), work-authorization without a named country — currently escalated.

The starting weak-field list lives in memory `career-agent-phase-e-weak-fields.md`.

## Goal

Add a **judgment tier** that answers these — grounded strictly in the candidate's profile + the job description — by **reusing the dashboard's existing, tested answer machinery**, with every answer a **draft behind the dry-run / human-gated-submit** safety net.

## Global Constraints

- **Grounded & truthful.** Answers derive strictly from the CandidateProfile / JD / (optional) research. Never fabricate experience or company facts. The reused `check_grounding` guard flags unsupported company claims.
- **Sensitive fields never auto-answered.** Demographics (gender, ethnicity, veteran) and attestations / T&C / e-signature are never LLM-answered — they always escalate (hard boundary, unchanged from Phase 3B).
- **PII stays local for the bulk.** Tier-2 uses the **local qwen** (Ollama); no résumé/profile data leaves the machine for qwen-answered fields.
- **Draft, not final.** Every judged answer is filled as a draft in **dry-run**; the human reviews before any submit. The judgment tier NEVER submits and NEVER ticks an attestation.
- **Bounded cost.** A per-application cap limits LLM/orchestrator calls.
- **Reuse, don't rebuild.** `draft_screening_answer`, `check_grounding`, `make_default_llm`, `CandidateProfile` are reused as-is.

## Escalation Ladder

| Tier | Who | Handles |
|------|-----|---------|
| 1 | Rules (Phase 3B) | structured fields — name, phone, country, city, résumé upload |
| 2 | **Local qwen** (this phase) | free-text fit answers + enum mapping, grounded in profile + JD — autonomous |
| 3 | **Orchestrator (Claude Code)** | the hard questions qwen is weak on — via an escalation channel (same pattern as OTP/collect); no Anthropic API client needed |
| 4 | Human | sensitive fields + what the orchestrator declines |

Tier 3 is present only when Claude Code is actively driving the run (supervised / testing mode). A fully autonomous headless run has no orchestrator → tier 3 is absent → qwen-only + escalate-to-human.

## Architecture — a judgment pass *after* the pure `map_screen`

`map_screen` stays pure (no LLM, no network) and unchanged. A new judgment pass consumes its `needs_human` list:

```
decisions, needs_human      = map_screen(form, profile, resume_pdf)   # pure, unchanged
answered, still_need, flagged = judge(needs_human, ctx, llm, cap)      # NEW
decisions += answered
# still_need -> human.collect(...) as today ; flagged -> surface for review
```

This keeps `map_screen` testable and isolates the LLM tier (testable with a fake `llm`, cap-controllable).

### New: `orchestrator/judgment.py`

```python
def judge(needs_human, ctx, llm, cap=6, orchestrator=None):
    """Try to answer the fields map_screen escalated. Returns
    (answered_decisions, still_need, flagged) where `flagged` is a set of refs
    whose answers tripped a grounding flag / general_fallback (surface for
    review). Never raises; never answers a sensitive field; never exceeds `cap`
    model calls."""
```

- `ctx` = a `JudgmentContext` dataclass: `job` (dict: title, company, description), `profile_text` (str), `research` (optional; empty by default), `resume_text` (str, optional).
- `llm` = tier-2 answerer, default `make_default_llm()` (local qwen). Injectable for tests.
- `orchestrator` = optional tier-3 callback `hard_questions -> {ref: answer}` (the file/signal channel; `None` in autonomous runs).
- `cap` = max tier-2+tier-3 calls per application.

**Per field in `needs_human`:**
1. **Sensitive** (`_is_sensitive(field)` — demographics purposes `gender`/`ethnicity`/`veteran`, or `attestation`) → leave in `still_need`. Never answered.
2. **Free-text** (`kind in {text, textarea}`, `purpose is None`) → `draft_screening_answer(job, field.label, profile_text, research, resume_text, llm)` → `{answer, flags, unsupported_company_claims}`. Fill as `FillDecision(action="fill", source="judgment")`. The **`source` value is the review signal** — `FillDecision` is unchanged; any decision whose `source` is `"judgment"` or `"orchestrator"` is a draft the human reviews (the trace/card highlights non-rule sources). `judge()` additionally returns a `flagged` set of refs whose `draft_screening_answer` raised grounding flags / `general_fallback`, so the caller can surface them prominently. If `general_fallback` **and** an `orchestrator` is available and cap allows → route to tier 3 instead of filling the weak qwen answer.
3. **Option/enum** (`kind in {select, radio_group}` with options, rules couldn't map) → `map_option(field.label, field.options, profile_text, llm)` → returns one of `field.options` or `None`. On a match → fill (coerced, `source="judgment"`); else → `still_need`.
4. **Cap reached** → remaining fields go to `still_need`.

`map_option` is a small, strict prompt: "Given the candidate fact and these options, return exactly one option verbatim, or NONE." The result is validated against `field.options` (never fill a non-option — the Phase 3B boundary holds).

### Tier 3 orchestrator channel (reuses the OTP/collect pattern)

`judge()` collects hard free-text fields into a queue file (`<scratch>/judgment_queue.json`: `[{ref, label, job, profile_text}]`) and polls a reply file (`<scratch>/judgment_answers.json`: `{ref: answer}`). When Claude Code drives the run, it reads the queue, drafts grounded answers, writes the replies; `judge()` fills them (`source="orchestrator"`, `review=True`). A timeout (or absent orchestrator) → the fields fall to `still_need`. This is the same background-signal mechanism validated for the OTP this session; no new transport, no Anthropic client.

### Wiring into the walk / entrypoint

- `step_engine.walk(...)` gains an optional `judge_fn` (default `None`). After `map_screen`, if `judge_fn` is set, `decisions += judge_fn(needs)[0]` and the remainder goes to `human.collect`.
- `apply.py` gains `--job-id` → loads the job (title/company/description) from the `jobs` table (`job_dashboard.db`) to build `JudgmentContext`; builds `profile_text` from the CandidateProfile; wires `judge` with `make_default_llm()`. A bare-URL run with no `--job-id` → no JD → `judge` still answers free-text from the profile-only fallback, or escalates.

## Data Flow

```
--job-id ──► jobs table (title/company/description = JD) ─┐
CandidateProfile ──► profile_text ───────────────────────┤─► JudgmentContext
                                                          │
per screen: map_screen ──► needs_human ──► judge(needs, ctx, llm, cap, orchestrator)
   ├─ sensitive ─────────────────► still_need (escalate to human)
   ├─ free-text ─► draft_screening_answer(qwen) ─► fill(source=judgment, review?)
   │                     └─ general_fallback + orchestrator ─► tier-3 queue ─► fill(source=orchestrator)
   ├─ enum ─────► map_option(qwen) ─► option or still_need
   └─ cap hit ──► still_need
decisions(rules + judged) ──► apply_decisions ──► advance ... (dry-run; never submits)
still_need ──► human.collect (unchanged)
```

## Error Handling

- `draft_screening_answer` / `map_option` never raise (wrapped); on failure the field stays in `still_need`.
- LLM (Ollama) unavailable → `general_fallback` answer or escalate; the walk continues.
- No `--job-id` / no JD → profile-only answers or escalate; never a crash.
- Orchestrator timeout / absent → hard fields escalate to human.
- Cap reached → escalate the rest.

## Testing

**Unit (no live LLM — fake `llm` fn):**
- Free-text field → `draft_screening_answer` (stub llm returns a fixed string) → filled, `source="judgment"`.
- Grounding flag / `general_fallback` → decision carries `review=True`.
- Sensitive field (gender/ethnicity/veteran/attestation) → stays in `still_need`, never answered.
- Enum: `map_option` returns a real option → filled & coerced; returns NONE / non-option → `still_need` (never fills a non-option).
- Cap enforced: with `cap=1` and two free-text fields, only one is answered; the other escalates.
- No-JD context → still produces a profile-only answer (fallback), no crash.
- Tier-3 channel: with a fake orchestrator returning `{ref: answer}`, a `general_fallback` field routes to it and fills `source="orchestrator"`.

**Live (manual, dry-run):** re-run the JPMC Oracle / Greenhouse walk with `--job-id`; confirm free-text questions now carry drafted answers (flagged for review), enum questions map or escalate, sensitive fields stay blank, nothing submitted.

## Out of Scope

- **Live company-research web-gathering** — `research` starts empty; `draft_screening_answer` gives a truthful general answer. Fast-follow.
- **Phase D graduated autonomy** — stays fully human-gated / dry-run; no learning, no auto-submit.
- **An in-process Anthropic/Claude API client** — the tier-3 "hard" path is the orchestrator (Claude Code) via the escalation channel, not a wired API client.
