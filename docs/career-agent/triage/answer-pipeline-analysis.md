# Answer Pipeline — Why Bank-Answerable Questions Escalated (30901 / 30604 / 29839)

**Date:** 2026-10-21 · **Author:** Backend Architect (subagent triage) · **Mode:** read-only analysis.
All experiments ran against the main repo's `data/jobs.db` opened `mode=ro` via URI
(`sqlite3 "file:data/jobs.db?mode=ro"`), code loaded from the worktree with `PYTHONPATH=src`.
No writes to the main repo. Experiment script kept at worktree root: `triage_experiment.py`.

---

## 0. TL;DR

| Job | Field | Bank had it? | Why it escalated |
|---|---|---|---|
| 30901 | `How Did You Hear About Us?` | **Yes** — exact/confident hit `referral_source` → `"Job Board"` (QA row: retrieval_score 0.94, source `qbank`) | Site-vocabulary reconciliation gap: Workday select/combo had no `Job Board` option (or lazily loaded none); the raw typed value failed → `[fill] did not take` → human |
| 30901 | `Country Phone Code*` | **Yes** — exact hit `country_phone_code` → `+91` (score 1.0) | Label-inferred shape `phone` requires ≥10 digits (`qbank_rules.py:183`), `+91` fails → downgraded `LIKELY` but **fill still attempted**; Workday dial-select needs `91`/“India (+91)” format, never normalized |
| 30604 | `Get email updates for the latest senior data scientist jobs` | **No** (experiment: top candidate 0.42–0.51, below FLOOR) | No deterministic decline-classifier: matching runs surfaced `marketing_emails` fact but only `attestation`-purpose checkboxes get the `_MARKETING` decline (screen_review.py:178); required checkbox with unknown purpose falls through `judge()` to `still_need` → Telegram human |
| 30604 | whole run | — | Node child died writing to a closed pipe (EPIPE) mid-walk: **0 `application_qa` rows, no screenshots, no pending-memory entry** — the failure left zero traces, so nothing could learn from it |
| 29839 | `What interests you about working for this company?` | Retrieval: NONE (ambiguous; top cand 0.59) | Correctly drafted by `judgment` tier; correctly blocked from autosubmit (`autonomy.STABLE_SOURCES` excludes `judgment`, autonomy.py:22,140) — policy worked as designed |

The bank itself is not the problem: **both 30901 fields were retrieved and the right values were attempted.** The failures live entirely in (a) value → page-vocabulary reconciliation, (b) an escalation gate that has no "decline me silently" rung, and (c) a feedback loop that fires only on the happy path and dies with the crash.

---

## 1. The question → answer pipeline, end to end (call graph)

### 1.1 Entry and wiring

```
apply_queue (--park)  javaDashboard/apply/queue_runner.py:86 argv() →
career_agent.apply.main (career_agent/apply.py:81)
 ├─ learns    = QBankMemory(conn, llm,_qllm, contact, job=get_job(job_id),
 │              high=cfg qbank_confident_min/100, facts_llm, skills)   apply.py:308-314
 │              ├── embed = MiniLM default (qbank.py:168-178)
 │              └── answer_field() is the bank's single brain (qbank_match.py:279)
 ├─ judge_fn  = judge(needs, JudgmentContext(job, profile_text, research, resume_text,
 │              ats_notes, story_text), llm, cap=20, min_conf, on_draft)  apply.py:256-268
 ├─ option_matcher = judgment.match_value_to_option  apply.py:274-281
 ├─ qa_rec    = QARecorder(conn, job_id); qa_rec.promote_embed = learn.embed
 │              → Telegram/human answers auto-promote to the bank   apply.py:209,316-318
 └─ engine    = graph (_run_graph, apply.py:12) for career-site URLs
                 or boards/run_board (apply.py:775-786) for board profiles
```

### 1.2 The shared ladder — `answer_fields` (used by BOTH the graph and boards)

`orchestrator/answering.py:123-161 answer_fields(fields, ctx)`:

1. **Trace** every field into `application_qa` (`qa.trace_all`, answering.py:131 → qa_recorder.py:20-29; stored: retrieval_kind/score/candidates/cc basis — this is the pipeline's primary observability).
2. **Prior human answers for this same job**: `qa_store.prior_answers` (qa_store.py:117) consumed by `_prior_human_answers` (answering.py:86-108) — source `human_prior`. Re-runs never re-ask.
3. **Question bank**: `learn.recall` (qbank_memory.py:73-93) → `answer_field` (qbank_match.py:279):

```
answer_field(conn, f)                                   qbank_match.py:279
 ├─ skip: kind file/button, purpose attestation, junk labels       :280-284
 ├─ split_escape: "type 'X' if …" peeled off                       :51-64
 ├─ skill-years structural hit (" Years … with Docker")  :285-288
 ├─ match_question(without_format_hint(q))                         :290 → 131-160
 │    ├─ qbank.exact(norm(label)) → CONFIDENT'exact' (1.0)         :133-135  (qbank.py:106)
 │    ├─ else: cosine(workings(MiniLM) x embed(question))          :139-147
 │    ├─ s1 < FLOOR(0.55) → NONE 'below floor'                     :148-149
 │    ├─ s1≥HIGH(0.87) & margin≥0.04 & no qualifier clash          :150-151 → CONFIDENT
 │    └─ else llm_pick → letter abc/NONE; pick=LIKELY else NONE    :153-157 (108-128)
 ├─ resolve_value: rule > profile_ref > stored answer              :163-190
 │    └─ qbank_rules.RULES (local_or_escape, preference, years_in_skill,…)  qbank_rules.py:23-159
 ├─ shape check: infer_shape(entry_shape → input_type → LABEL regex)  qbank_rules.py:178-197
 │    shape_ok fails → downgrade to LIKELY, **value still included**   qbank_match.py:326-330
 │    fit_option(value→page options): exact→_coerce_option→LLM      :330, 193-207
 │       (screen_review._coerce_option screen_review.py:80-100;
 │        judgment.match_value_to_option judgment.py:85-110)
 │       NO options at all (lazy combobox) → raw value passes      :196-197
 └─ fallbacks when entry unmatched: compose from related facts     :301-316
      (_compose_from_facts → qbank_compose.related_facts/compose;
       yes/no-from-facts; MIN_RELEVANCE 0.40/0.50)                 qbank_compose.py:20-22
```

4. **Rules/proficients tier**: `map_screen` (screen_review.py:157-222) — standard answers, purpose-driven profile values, attestation tick, **marketing decline ONLY inside the attestation branch** (`_MARKETING`, screen_review.py:28; applied at 178).
5. **Judgment tier**: `judge()` (judgment.py:169-252) — selects via `map_option` (prompt = ATS notes + `profile_text[:1500]`), drafts essays via longform/`draft_screening_answer` (job title/company/description as ground), combobox free-value via `judge_combobox_value`, cap 20 calls; **unknown-purpose non-text field → `still_need` (escalate)** at :238.
6. **Shaping before fill**: `shape_value` (money/number units, answering.py:74-84) and `national_number` (strip `+NN ` from phone boxes when a dial field exists, answering.py:52-70).

### 1.3 Applying, detecting failure, escalating

```
fill_node (graph.py:309-427) ─► fill_top_down (top_down.py:60-136)
     per field: deps.fill → read_back → EMPTY?
       → "[fill] did not take: label = value"      top_down.py:91-97
       → field appended to `needs` (→ human)      ← THE ONLY remedy is a human ask
when reveals new fields → answer_fn(fresh, ctx) again (top_down.py:120-126)
needs → human_gate interrupt (graph.py:430-451)
outer loop (apply.py:37-76):
     → judge_fn RE-try (stragglers; cap reset)     apply.py:59-67  "[judge-retry]"
     → telegram / cli collect                      apply.py:70-73
     → resume graph → fill → record_answers        graph.py:442-446
boards variant: boards/run.py:279-296 _answers → _ask:238 → _ask_human:255-276
     → EscalationCollector / TelegramCollector (see §1.5) → record_answers
```

### 1.4 Where escalation is DECIDED (exhaustive list of the deciders)

| Decision | Site | Trigger |
|---|---|---|
| Fill failed | `top_down.py:91-97` | read-back empty after applying → field goes to needs with its real label |
| Bank NONE | `qbank_match.py:149,156,324,336` | below floor / LLM said none / no answer for entry / no option fits |
| Rules pass nothing | `screen_review.py:221` | unknown purpose + required (or prose/text) |
| Judge declines | `judgment.py:184,188,194,203,211,238` | optional non-text skipped, cap hit, option None, weak draft, unknown kind |
| Required marketing checkbox | `qbank_memory.py:86-89` (recall) | "No" on a REQUIRED checkbox cannot be declined → left to mapper (=human) |
| Pickup of human answers | `graph.py:430-451` / `apply.py:37-76` / `boards/run.py:255-276` | interrupt loop, judge-retry first, then Telegram |

**There is no decision point that names a "decline" class** — the closest is the two marketing regexes (`_MARKETING` uses inside attestation only, screen_review.py:178; board `_untick` boards/run.py:122-137, which fires only at the final submit and only on unchecked-at-that-moment boxes). Everything else is binary: filled → escalated.

### 1.5 What context reaches the LLM where it matters

| Tier | Prompt contents | Missing |
|---|---|---|
| Bank lane (exact/embed) | question only; llm_pick sees 1-3 bank questions (qbank_match.py:114-119) — faithfulness by spec | deliberately job-blind |
| llm_pick wording disambiguation | bank questions + slot notes | page OPTIONS list! The LLM picks "same question" without seeing e.g. the field is a phone-code select |
| `fit_option` LLM rung | label + value + live options (judgment.py:92-98) | no site/DSL context, no synonyms table mismatch ("Job Board" vs "Job Portals (Naukri…)") |
| compose-from-facts | question, field kind/options, ≤6 bank facts, today (qbank_compose.py:92-114) | **no job description, no company** (rarely needed, but "how did you hear" composing can't see the JD/brand) |
| judgment `map_option` | label, options, ATS notes, profile_text[:1500] (judgment.py:63-68) | **no JD, no company** even though judgment.py:17-24 carries one — selects/combobox never see `ctx.job` |
| judgment essays | job (title/company/description) + profile + resume + story (apply.py:256-258, judgment.py:220-222) | ok |
| Telegram ask | label + numbered options (collector.py:125-137); JD excerpt ONLY if `_COMPANY_Q_RE` matches the question (collector.py:21-27,68-73); whole JD + company page sent once upfront (up to 3800 chars, escalation.py:19-31) | options may be empty (lazy combobox), so the human is asked to type with no choices shown (collector.py:192-198) |
| submit-time self-check | read-back values vs decisions | only kept/edited signals; field-idempotency of site option lists is never persisted back |

**Context drops (file:line):** (a) `map_option`/`judge_combobox_value` drop `ctx.job` entirely — judgment.py:192-206 build the prompt from `profile_text` only; (b) `profile_text` is hard-truncated to 1500 chars at judgment.py:68; (c) Telegram combobox fallback asks without options (collector.py:192); (d) the escalation decision (top_down.py:91-97) ships the failing field to the human with **no error summary, no options, no bank answer it tried** — note it *did* print value to stdout, not to the human message; (e) facts-plan (`facts.py`) sees profile facts only.

---

## 2. Failure post-mortems (evidence)

### 2.1 Job 30901 — Workday "How Did You Hear About Us?" + "Country Phone Code*"

DB evidence (`application_qa`, run 8e4d72e431354907a6176ddb6080c9e2):

```
ref #source--source            label 'How Did You Hear About Us?*' kind combobox options_json ''
     retrieval shortlist referral_source 0.94  source qbank  status filled  answer 'Job Board'
ref #phoneNumber--countryPhoneCode  label 'Country Phone Code*'   kind combobox options_json ''
     retrieval exact country_phone_code 1.0   source qbank_likely  status needs_answer  answer '+91'
     basis: "likely: shape phone failed"
(plus #languageSelectorButton qbank_likely 'Fluent', #phoneNumber--phoneType 'Mobile',
 radio group 'Have you previously worked … MKS Inc' → No, all needs_answer)
```

Experiment (off these exact inputs, `triage_experiment.py`):

```
"How Did You Hear About Us?"   exact-if-wording; shortlist referral_source → 'Job Board'
   fit_option vs 6 Workday-style options [LinkedIn, Indeed, Google, Referral,
   'Job Board - Other', Other]                      → None     ← nothing matches
   fit_option vs 0 live options (lazy combobox)     → 'Job Board' raw  ← passes, untyped
"Country Phone Code*"   exact country_phone_code 1.0 → '+91'
   infer_shape → 'phone' (label regex qbank_rules.py:183) ; shape_ok('+91') False
   fit_option vs ['+91 (India)','+1 (United States)','India (+91)','+91','+1'] → '+91' raw
```

**Chain of failure (ranked):**
1. **Option-vocabulary reconciliation gap.** The bank entry holds `Job Board` (qbank_entry.referral_source) but Workday's select enumerates its own sourcing taxonomy; neither the entry's `synonyms` (empty on the row) nor a rule maps `Job Board` → that list. `fit_option` will never fabricate a mapping when nothing matches → escalation. With lazy options the raw text is typed and dropped (filler `_pick_combobox` fails silently after one pass, filler.py:70-136; read-back empty → top_down.py:97).
2. **A shape check that reports but does not shape.** `+91` fails the phone-shape check (>10 digits, qbank_rules.py:183) because the LABEL says phone — but the value is a standalone dial code. It was `LIKELY`-filled anyway (qbank_match.py:329 only notes, per spec "review it before submit"), landing as `qbank_likely` in a select where `+91` (with the plus) was not an option (Workday stores plain `afterthought: "91 (+91)"`-style codes; see the 247-option phone list comment in filler.py:96-99).
3. **No re-fill with live options, no failure-driven learning.** The combobox filler gets ONE attempt with live options (filler.py:70) with `_coerce_option`+LLM matcher available, but its matcher prompt (judgment.py:92-98) doesn't see the bank entry, and after "did not take" the ONLY path to the human has no intermediate step that re-reads the live option list and re-asks "then which of these?" before Telegram.

Note the whole escalation decision for a broken filler is **symptom-to-human**, i.e. the pipeline pays the human for the site's taxonomy.

### 2.2 Job 30604 — Indeed "Get email updates..." + EPIPE crash

- Retrieval: those labels embed at **0.42–0.51** against the bank's nearest candidates — below FLOOR. It is a *marketing opt-in* unanswerable by the bank, by design (answers not stored).
- The only marketing decline paths are `attestation`-purpose checkboxes (screen_review.py:178) and `boards._untick` pre-submit (boards/run.py:125-137). A REQUIRED checkbox with unknown purpose reaches `judge()` line 184/238 → `still_need` → Telegram. For a non-required one, `map_screen` leaves it blank silently (screen_review.py:220-222 prose/text only) — so 30604's ask means Indeed surfaced it as required (or radio/select kind).
- No decline-classifier exists for *any* kind: `judge()` line 184 explicitly skips "optional non-text" but never refuses required marketing asks; there is no `answer_policy` gate.
- **Crash trace hygiene:** `grep EPIPE` finds no Python handler. Node `_epipe` crash killed the run before `_write_run_log`/`_append_pending_memory` (apply.py:602-604, 640-676) executed: job 30604 has **0 `application_qa` rows, no `agent_runs/30604` artifacts, jobs.status='failed'** (sqlite: `SELECT COUNT(*) FROM application_qa WHERE job_id=30604 → 0`). The escalation was sent (Telegram), the run died mid-wait, nothing else survived. `_append_pending_memory`/`promote_answer` are in-process steps — a hard child death takes the learning loop down with the process.

### 2.3 Job 29839 — Wellfound essay (policy working correctly)

"What interests you about working for this company?" embeds to 0.59, ambiguous, no bank entry → none bank-matched. `judge()` routed it through longform/`draft_screening_answer` → decision source `judgment` (judgment.py:234). `autonomy_report` blocks anything not in `STABLE_SOURCES` (autonomy.py:22, 140-150) → dry-run stop. That is the intended guardrail; the only design question is whether `promote_answer`'s `_COMPANY_SPECIFIC` guard (qbank_promote.py:19-23) then correctly keeps it application-local — it does.

---

## 3. The general gap: what guarantees the NEXT similar question is answered?

What exists today:

| Loop | Where it fires | Copies to `qbank`? | Gap |
|---|---|---|---|
| Telegram/human answer → promote | `qa.answered` → `promote_answer` (qa_recorder.py:67-76, qbank_promote.py:26-44) | YES auto (`promote_embed` set apply.py:318) | proposes only-when: no company-specific, not sensitive, not file. **But it runs only if the answer was received in-process** — a parked reply typed later on the tracker does NOT go through it |
| Tracker reply → save-as | `POST /api/jobs/{id}/questions/{row}/reply` (qa_routes.py:206-232) `save_as=once|new|wording` | MANUAL choice per question — `once` (the default) saves no bank entry | no prompt to save as wording when the label looks bank-matchable; no proposal engine |
| Submit read-back → approvals | `autonomy.record_submission` (autonomy.py:96-113) | +1 approval for `qbank`/`qbank_likely` entries | **`SELECT SUM(approvals>0) → 0`** over all 98 entries: either never reached (few confirmed submits) or never wired for telegram-promoled entries — graduated autonomy is effectively cold |
| Run digest → memory file | `_append_pending_memory` (apply.py:640-676) → `data/pending_memory_updates.md`; `ats_promote` folds ONLY the `trail:` blocks at next drain (memory/ats_promote.py:18-100) | escalated_fields live in the same md file but are consumed by hand by "the next Claude session" (docstring) | the qbank half of the digest has NO automated promoter — bilingual process on a human habit |
| `answer_lesson` table | schema exists (`lesson` rows for fact lever) | **zero code readers** (grep) | dead table |
| Retrieval regression check | `scripts/qbank.py calibrate` hold-one-out + suggested FLOOR/HIGH/MARGIN (qbank_admin.py:32-65) | no data flow into runtime | manual, offline |

**Missing links (the real gap):**
1. **Failure-after-fill does not enrich the entry**: "did not take" never writes back which live options the site offered, never generates synonym variants, never incurs on the entry a `many_wrong_options→review` state. The very failure that reveals `"Job Board" isn't an option on mksinst.wd1…` is dumped to stdout only.
2. **Fill-failure→human is paying full price**: escalation for an option-mismatch question should be one click over the site's real options (a mini menu re-collected from the page), not a blind typed answer. TelegramCol offerer already renders options when present (collector.py:125-129), but the failing field was an empty-options combobox → free text ask, and the human's answer then re-promotes with the same wording and the same vocabulary gap for NEXT time (unless they happen to edit the entry).
3. **No promotion of judge-retry straggler answers**: judge-retry answers (apply.py:59-67) arrive BEFORE the interrupt; the ones answered by `map_option` at that point fill and are recorded (`qa.decision` source judgment) but the site's CHOICE is not folded into the bank (nor into the dial/source entry as a site-specific option/synonym).
4. **Approvals counter is inert** — graduated autonomy (the reward for answers that keep surviving) has never been earned: entropy stays at "ask again", and the bank stays valuable only for exact wording repeats.
5. **Crash durability**: escalation moments are exactly when families of hard-to-fill questions appear; a process death loses QA rows?? No — rows are committed (qa_store.record commits); but the escalated-commit-loss path for the boards run and any screenshots/pending-memory for THIS job is dead when the child is killed. EPIPE = the pipeline's most valuable feedback moment (the human is mid-answering) is also its most fragile.

---

## 4. Candidate architectures (design competition, NOT to implement)

Four candidates are proposed against the mission: "bank-answerable questions must never be escalated or dropped". They stack partially but are written as a competitive comparison.

---

### Candidate A — Vocabulary Bridge: two-stage retrieval + exact-option reconciliation

**Thesis:** the failures were VALUE problems, not MATCHING problems. Keep the bank's faithful judgment-free core, and add a *reconciliation layer* between "resolved value" and "page field".

**Components:**
1. `SiteOptionReconcilers` (new module `memory/option_vocab.py`): consumes `(entry, value, shape, live_options, site_kind)`.
   - normalization ladder: strip `+`/parens; format-aware rewrites (`+91`→`91`, `India`→`India (+91)`), a numeric-only dial-map (reuse `_DIAL_OPTION` answering.py:38), acronyms ("Job Board" → {LinkedIn, Indeed, Naukri, Portals}), currency ("LPA"→"INR" and vice versa)).
   - bounded LLM rung: one `match_value_to_option` call **with the bank question + entry answer + site-taxonomy options list** asked to pick a page option that **means the same sourcing event**, not the same string (reusing the existing matcher judgment.py:85-110).
2. Entry-level state: `qbank_option_map(site_hash, entry_id, site_option)` — a per-site dictionary the reconciler both READS and LEARNS (promote from §B loop). One row per (site, entry, option).
3. **Fail-forward:** if the reconciler returns None, the fill decision is *simulated*: open the combobox read-only, get live options, and ask the human the REDUCED question "which of these means 'Job Board'?" — the collector already supports numbered options (collector.py:125-129); extend it to collect options read live from the widget instead of asking for typed text.
4. Guard-rails: the label-inferred `phone` shape must be suspended when `has_dial_field(fields)` is True (from answering.py:52) — the value is then shaped by `[0-9]{1,3}` only in the dial select and by strips elsewhere; add `dia_code` shape.

**Failure modes:** mapping wrong (a teammate asks "Job Board" → we pick "Company Website") mitigated by entry-level verification state and the review-block on `LIKELY` reconciliations (same as today, qbank_likely); stale site vocab after relaunch (rebuild from live page); over-fitting to one site's weirdness without generalizing — mitigated by storing on entries, not on hard-coded rules.

**Migration risk:** none for DB (additive table); behavior change: MORE fills succeed; risk of bad auto-answers rising if verification threshold is set low — gate new map rows behind one review/submit.

**Testability:** golden-case tests exist naturally: for every (entry, site-option) pair already seen, the reconciler must return the known option; calibrate extension (`scripts/qbank.py calibrate` analog: `calibrate_vocab`) measures accuracy over stored pairs. Add unit tests for `dia_code` shape and `_MARKETING`-like label adversarial cases.

**Effort:** ~3-5 dev-days for the reconciler + dial shape; +2 days for site-vocab table + promotion write path; +1 day tests. **Medium-low risk, high direct payoff for 30901-class failures.**

---

### Candidate B — Closed feedback loop (Telegram/tracker → bank, automatically)

**Thesis:** every human-resolved answer that contains a fact worth reusing must flow into the bank automatically — deduction free for the next application — including answers typed on the tracker, on Telegram-amid-a-crash, and judge-retry straggler values.

**Components:**
1. **Schema** (additive):
   ```sql
   CREATE TABLE qbank_candidate (
     id TEXT PRIMARY KEY, question TEXT NOT NULL, answer TEXT NOT NULL,
     provenance TEXT NOT NULL,        -- telegram|tracker|judge_retry|fill_failure
     job_id INT, run_key TEXT, site_hash TEXT,
     label_options_json TEXT,         -- dump of the site's listed options at ask time
     failed_value TEXT NULL,          -- value that didn't take, if any
     state TEXT,                      -- pending|accepted|rejected|merged
     dedupe_group TEXT, embedding BLOB, created_at …, updated_at …);
   ```
2. **Writers:** (a) `TelegramCollector`/`EscalationCollector`/`CliCollector` call a `feedback.record(field, answer, provenance)` even when the process is mid-ask (write-through); (b) `promote_answer` moves from "auto-insert" to "auto-insert + candidate registry + wording variant recording" (dedupe via `embedding cosine(distance<0.08)` against existing entries plus the digest in `qbank_wording.norm`); (c) the tracker reply route stores every `save_as=once` as a candidate an evaluator script (`scripts/qbank.py curate`) later merges; (d) `fill_node`/`judge-retry` answers record provenance judge_retry.
3. **Curation step:** a dashboard card + CLI `scripts/qbank.py curate` shows pending candidates grouped by dedupe group with a one-key "accept as new entry / accept as wording of an existing entry / reject"; `accept as wording` records the site-specific option list from `label_options_json` into `qbank_option_map` (feeding Candidate A's table).
4. **Approvals bootstrap:** when human confirms a promoted entry's answer once (e.g. the telegram reply that repeats the answer the entry already holds) → set `approvals=1` so the entry stops behind `LIKELY` and joins `STABLE_SOURCES`-eligible levels of autonomy after 3 (matching AUTONOMY_THRESHOLD autonomy.py:33).

**Failure modes:** duplicates creeping in (dedupe threshold catches near-identical labels; manual merge UI is the backstop); the registry growing unbounded (retention: tail-of-promoted candidates only); auto-accept one bad answer → poison (mitigated by the dedupe+state machine: nothing accepted on first sighting unless the recorded label options exist and value fits; telegram answers on marketing fields (Candidate C) never store).

**Migration risk:** low — additive routes; existing `promote_answer` preserved; requires one curation pass (a single CLI run) to clear the current backlog. The `application_qa` rows already carry 1077 `needs_answer` rows of reading material for the first curation run.

**Testability:** every loop is a pure function (`feedback.record` writes; `curate` reads); a fixture-run can replay historical Telegram transcripts; calibrate-like sweep tells you "of N historical needs_answer labels, K would have been retrieved by the bank after promotion" — direct, quantitative.

**Effort:** ~2-3 days schema+writers, 2 days curate CLI+dashboard card, 1 day approval bootstrap. **Low-low risk; the structural payoff.**

---

### Candidate C — Decline-classifier gate before any human escalation

**Thesis:** there is a class of questions the agent must never ask: newsletter/job-alert/marketing/connect prompts and their Yes/No variants ("Get email updates…", "Follow company", "Notify me…"). They deserve a deterministic gate with a DECLINE action, not the LLM and not the human.

**Components:**
1. `orchestrator/decline_class.py`:
   ```python
   DECLINE = "decline"; ASK = "ask"; SKIP = "skip"
   def classify(f, job) -> str       # deterministic, no LLM
   ```
   Runs BEFORE `map_screen`/judge. Patterns supersample `_MARKETING` (screen_review.py:28): `newsletter|job alerts?|email updates|notify (me|you)|similar jobs|marketing|talent community|follow·ing company|stay (informed|updated)|get (updates|notifications)`, plus structural checks: kind in {checkbox, radio_group} AND question not required for application eligibility…; when the site forces required marketing, answer-*No*/decline is written as a FILL decision with source `decline_class`, optionally unticking at submit (reusing boards._untick).
2. **Integration:** in `answer_fields` before map_screen (answering.py:139) → `FillDecision(ref, kind, label, "No"/None, action for kind, "decline_class")` for asks, and `needs.drop` for skip-class (search navs, `#countrySelector` decorative). Fields not decided by the gate pass through unchanged.
3. **Policy surface:** one dashboard setting `decline_marketing=1|0|ask` (unlike add-hoc regex patches to _untick per board). The gate replaces the two current special-cases (attestation branch line 178, boards._untick line 127) with a first-tier ruleset — single point of policy.
4. **Storage pragmatics:** declined asks are recorded in application_qa as source `decline_class`, outcome `skipped-by-policy`, so the audit trail stays.

**Failure modes:** misclassification over-declined a real question ("Are you interested in job updates about this role?" — actually required to answer; mitigation: required checkbox declines are recorded and if the submit bounces (boards.run "validation_error") the field is re-asked through the existing bounce path (boards/run.py:406-418) — the retry loop is already built); strings drift (a marketing pack per site) — keep the list in `qbank_seed.json` so it ships with the bank and is versionable; audits show up in the same application_qa query surface.

**Migration risk:** low; covers 30604-class asks; does nothing for 30901-type option-vocabulary gaps (that's Candidate A's territory).

**Testability:** the trickiest bitwise: pure regex+shape → unit tests table-driven; threshold 30604/30580 historical labels as fixtures. The classifier's decision trace is one column (`decline_reason`) in QA recording making the logs self-auditing.

**Effort:** ~1.5 days. **Smallest, most isolated candidate; cheapest bug-farm.**

---

### Candidate D — Answer-policy contract (observability + crash-durability)

**Thesis:** make "what happened to each unanswered field" a first-class, always-written artifact — every field must terminate in exactly one policy-verdict label — so any failure (bank miss, declined escalate, crash) is decision-auditable and any crash preserves the audit trail.

**Components:**
1. **The contract:** for every field that appears on a form, `question_policy(field) -> verdict` where verdict ∈ 
   `{ bank_exact | bank_heuristic(composed|shortlist|llm) | rule+profile | plan_from_facts | judgment_options | judgment_text | decline_class | unresolved_filler_failed | human_asked | human_skipped | crash_interrupted }`, plus reason. Enforced by writing the verdict enum into application_qa (`policy_verdict` col) at each transition; a run-level validator asserts non-null at the end (and prints a histogram).
2. **Crash-proofing:** (a) write policy verdicts append-only to a journaling jsonl file under `agent_runs/<job_id>/decisions.jsonl` AS they happen (already got `run_log` for boards; extend per-run); (b) a watchdog child (already avail: `apply/submit_watch.py`/`stall.watch`) marks `crash_interrupted` on exit and enqueuing cleanup steps: reprocess application_qa rows into candidates (loading from Committed rows — qa store already survives); (c) Telegram asks are shipped through a persistent queue table so an ask survives process death and the reply can be consumed by a future run (`telegram_replies` table; collector drains from the table not the live socket).
3. **The missing metrics:** per-source fill success rate (bank vs rule vs judgment vs human), escalation-per-run, "resolution turnaround" (ask→answer→promote), option-reconciliation hit rate per site (from Candidate A's table). All computable from the contract columns alone (+ Candidate B tables).
4. **Client of the feedback loop:** the daily curation ("here are 12 unresolved fillers last week; 6 look bankable") becomes a query over the contract columns. Moves qbank-growth from anecdote to measured.

**Failure modes:** contract drift (new sources must register a verdict — enforce by enum check in QARecorder `decision()`); overhead (one json line per decision; trivial vs the fill); masking (a "decline_class" verdict must not hide a real question — keep `required` flag packing); if Telegram replies are persisted, stale replies could answer the wrong run (mitigate: reply-ID-to-run-key binding at ask time).

**Migration risk:** low-medium; the biggest change is discipline (every answering path must emit the verdict); requires no site-behavior change; if the EPIPE class of crash recurs, the run at least leaves a full decision log, screenshots timestamps, and recoverable asks.

**Testability:** validator IS the test (fails loudly on verdict gaps); replay 30901/30604 against the contract and inspect the summary.

**Effort:** ~3 days for verdicts+jsonl journal+validator; +2 days for telegram reply persistence and a recovery path; **high payoff as the foundation the other three report through.**

---

## 5. Comparison & verdicts

| | A vocab-bridge | B feedback loop | C decline gate | D policy contract |
|---|---|---|---|---|
| Kills 30901 failures | ✔ (both) | partial (prevents recurrence) | ✗ | observability |
| Kills 30604 ask | ◑ no option-vocabulary mismatch class | partial (prevents recurrence) | ✔ direct | observability |
| Generalizes to NEW question sets | ✔ per-site vocabulary | ✔ bank grows on every answer | ◑ only marketing class | ✔ meta |
| Crash-durability | ✗ | ◑ | ✗ | ✔ |
| Riskiest assumption | LLM reconciliation trust | auto-accept poisoned data | regex false-positives | adoption of new discipline |
| Effort | ~5-7 d | ~5 d | ~1.5 d | ~5 d |
| **Recommended order** | 2nd | 3rd | **1st (smallest, cheapest)** | alongside (crosscutting) |

**Stack behavior:** all four compound: C removes non-questions before they reach A; A fills vocabulary gaps bank entries can't; B converts whatever still has to reach a human into permanent knowledge; D makes every one of these decisions visible and survives process death. If forced to choose only two: **C + B** (policy + loop) — they address the largest harm (wasted human attention and lost learning) — with D's verdict columns being cheap enough to fold into B's schema directly.
