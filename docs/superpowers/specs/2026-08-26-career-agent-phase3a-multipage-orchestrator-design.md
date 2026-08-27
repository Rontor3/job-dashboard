# Career Agent — Phase 3A: Multi-Page Orchestrator (résumé-driven) — Design Spec

> **Status:** design, pre-implementation.
> **Scope:** the first slice of Phase 3 — an orchestrator that **walks a multi-screen job application** from a target URL, filling from a **structured candidate profile extracted from your résumé draft**, escalating what it can't fill to you over Telegram, clearing gates via the Phase-2 remote-solve, and advancing screen-by-screen until a terminal state. Reuses Phase 1/2 wholesale.

---

## 1. Goal

Given a target (a career-page/ATS URL + your profile + résumé), **complete a multi-page application**: perceive each screen → fill known fields → escalate unknowns → clear gates → advance → repeat, stopping at an approval-gated (or, in production, autonomous) submit. This is the "take it from here" piece: Phase 1/2 proved single-screen perception/fill and phone captcha-solve; 3A makes it walk the *whole* flow.

## 2. Scope & non-goals

**In scope (this slice):**
- The step-loop that walks screens.
- Résumé draft → structured **CandidateProfile** extraction (one bounded LLM pass, cached).
- A **richer, résumé-driven field mapper** (many more purposes; repeating groups like multiple work-experience rows).
- **Per-screen human escalation** ("fill these fields") over Telegram.
- **Advance** (find/click Next/Continue/Submit) + **step-change detection**.
- **Submit boundary**: approval-gated by default; an explicit autonomous mode.

**Explicitly out (later sub-projects, stubbed or escalated here):**
- **B — Durable state machine** (LangGraph checkpointer/resume). 3A is a plain loop, structured so B can wrap each step later.
- **C — Gmail OTP connector.** OTP gates **escalate** for now.
- **D — Persistent memory + graduated-autonomy learning.** 3A re-derives each run; "approve-a-few-times → autonomous" is not learned yet.
- **E — Judgment tier for novel questions.** Screening questions / essays **escalate** to you; the LLM here is bounded to *résumé extraction only*.

## 3. Architecture — step-loop now, LangGraph later

A plain Python **step-engine loop**. Each iteration handles exactly one screen and returns a typed `StepResult`, so sub-project B can later wrap one iteration = one LangGraph node with a checkpointer, without rewriting the logic. No premature durability.

## 4. Data source — a CandidateProfile derived from your résumé draft

The orchestrator fills from a structured profile richer than Phase-1's flat `application_profile`:

```
CandidateProfile:
  contact:      { full_name, email, phone, location, links… }   # from application_profile
  experiences:  [ { company, title, start, end, bullets[] } ]   # from résumé
  education:    [ { school, degree, field, start, end } ]        # from résumé
  skills:       [ str ]                                          # from résumé
```

- **Source:** the dashboard's current **résumé draft** — the `src/job_dashboard/resume_segments/` blocks (`experience-*`, `project-*`, `skills-*`, `education-*`, `header-contact*`) plus `application_profile`.
- **Extraction:** one **qwen3:14b** pass turns the résumé text into the schema above (a bounded "extract structured fields" task — *not* open-ended judgment), reusing the dashboard's Ollama client pattern (`job_dashboard.resume.resume_llm.make_ollama_llm`: POST `/api/generate`, `format: json`). Result cached to JSON so it runs once per résumé.
- Extends the Phase-1 **Factual Core** to hold this profile. PII stays local; the cache never enters git.

## 5. The per-screen loop

For each screen, `step_engine` does:

1. **Perceive** → Form Model (Phase 1 `snapshot_form`).
2. **Gate check** (Phase 1 `classify_gate`):
   - interactive captcha → **remote-solve** (Phase 2).
   - `otp_email`/`otp_sms` → **escalate** (C not built).
   - `cloudflare_interstitial`/other → **escalate**.
   - `none`/`cleared` → proceed.
3. **Map + fill** from the CandidateProfile (§6). Collect required-but-unmapped fields and novel questions as `needs_human`.
4. **Escalate the screen** if `needs_human` is non-empty (§7): send you the list; apply your answers.
5. **Advance** (§8): find and click the screen's Next / Continue / Save-and-Continue / Submit control.
6. **Detect the result** via screen signatures (§8): advanced → next screen; unchanged + validation errors → surface + re-escalate; confirmation/terminal → done.
7. **Terminate** on: confirmation page, no advance control, unrecoverable gate, **max-steps cap**, or human abort — else loop.

## 6. Field mapping — résumé-driven, with repeating groups

Extends `orchestrator/mapper.py`:
- **More purposes:** `employer/company`, `job_title`, `start_date`, `end_date`, `degree`, `school`, `field_of_study`, `gpa`, `skills`, `summary`, on top of Phase-1's contact/auth set.
- **Repeating groups:** detect a repeating section (a "Work Experience" block with an "Add another"/"+" control, or indexed rows) and fill successive rows from `experiences[]` / `education[]`.
- **Purpose → CandidateProfile resolver:** `employer` → `experiences[i].company`, `skills` → joined `skills[]`, etc.
- Anything unmapped-but-required, or any free-text question, → `needs_human` (never guessed).

## 7. Human escalation — the "fill these fields" interaction

A new human-loop interaction alongside approve/remote-solve:
- `collect(fields) -> answers`: sends a Telegram message listing each unfilled field / novel question; you reply (tap for choices, free-text for the rest); the orchestrator maps replies back to fields and fills them.
- Extends `integrations/human_loop.py` + the Telegram client. (Free-text → scoped memory rules is D; here we just capture and apply the values.)

## 8. Advance + step-change detection

The hard part, same shape as Phase-2's captcha-resolve:
- **Screen signature** = `(url, sorted field labels, step-indicator text)`.
- Capture the signature, click the advance control, `wait_for_load_state("networkidle")` to settle, re-signature.
- **Changed** → advanced. **Same + visible validation errors** → didn't advance (surface errors, re-escalate). **Confirmation/terminal markers** → done.
- Advance-control finding: `get_by_role("button"/"link", name=~ Next|Continue|Save and continue|Submit|Review)`, most-specific-first; never click a control matching destructive/`Cancel`/`Back`.

## 9. Submit boundary

- **Default: approval-gated.** At the final submit, send the full review card (Phase 1 `render_card`, extended across screens) via Telegram; submit only on approval.
- **Autonomous mode** (`--autonomous` / setting): submit without prompting. For production, per the product decision (testing = approval; real = autonomous).
- Graduated-autonomy *learning* (approve-N-times → auto) is **D**, not here.

## 10. Safety & boundaries

- **Max-steps cap** (default 15 screens) — no runaway walks.
- **Attestations never auto-ticked** (Phase 1 rule holds) — always surfaced.
- **Dry-run:** the whole walk runs without ever submitting until approval/autonomous.
- **No evasion** (unchanged): gates are detected and escalated/human-solved, never bypassed.
- **Human abort** at any escalation.

## 11. File layout (new + extended)

```
src/career_agent/
  orchestrator/
    step_engine.py      # the per-screen loop; StepResult; terminate conditions
    advance.py          # find advance control + screen-signature/change detection
    screen_review.py    # build the "needs_human" set + apply collected answers
    mapper.py           # EXTEND: more purposes + repeating groups + profile resolver
  memory/
    candidate_profile.py# résumé draft -> CandidateProfile (qwen3:14b extract) + cache
  integrations/
    human_loop.py       # EXTEND: collect(fields) -> answers
    telegram/…          # EXTEND: field-collection message + reply parsing
  apply.py              # NEW entrypoint: walk a full application (vs run.py single-page)
tests/career_agent/…
```

## 12. Testing

- **Pure:** CandidateProfile extraction (inject a fake LLM → assert schema); advance-control finding (Form Model fixtures); screen-signature change detection (before/after); repeating-group mapping (experiences[] → rows); step-loop control flow with a fake page + injected perceive/gate/advance (like the Phase 1/2 run-flow tests); submit approval-gated vs autonomous.
- **Browser (skip-marked, `RUN_BROWSER_TESTS=1`):** a 2–3 page linked-by-Next HTML fixture the loop walks end to end, filling from a fixture profile.

## 13. Reuse from the dashboard

- `job_dashboard.apply.store` (application_profile), `resume_segments/` (résumé draft), `job_dashboard.resume.*` (CV render for upload steps), `resume_llm.make_ollama_llm` (Ollama client for extraction).
- From Phase 1/2: perception, gate_probe, remote-solve, filler, review_card, human_loop/TelegramApprover.

## 14. Global constraints

- No evasion in-tree; gates escalate or are human-solved, never bypassed.
- Attestations never auto-answered; submit approval-gated unless explicitly autonomous.
- The only LLM use is bounded résumé→JSON extraction on **local qwen3:14b** — no judgment-tier answering of novel questions in this slice.
- Max-steps cap; dry-run capable.
- PII (CandidateProfile cache) stays local, never committed; files < 500 lines; tests under `tests/career_agent/`.
