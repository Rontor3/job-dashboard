# Red-Team Review — answer-pipeline-analysis.md candidates (A/B/C/D)

**Date:** 2026-10-21 · **Author:** Code-Redteam subagent · Read-only against main repo.
Every file:line in backend-architect's brief was re-checked against the actual source and `data/jobs.db` (opened `mode=ro`). Verdict at §5.

---

## 1. Citation audit

Legend: ✅ verified · ⚠️ direction holds, line/key wrong · ❌ doesn't hold.

| Brief claim | Reality | Status |
|---|---|---|
| `qbank_match.py` fit_option ~193-207; raw value passes with no options (:196) | `fit_option` 193-207; `if not options: return value` 196-197 | ✅ |
| `qbank_match.py` shape-fail downgrade 326-330, value still filled | 326-329 `LIKELY, f"shape {shape} failed"`; value still passed to `fit_option` 330 | ✅ |
| "Bank NONE" deciders `qbank_match.py:149,156,324,336` | all four exact (`below floor` 149, `llm: none` 156, `no answer for entry` 324, `no option fits` 336) | ✅ |
| `qbank_rules.py:183` — phone ≥10 digits **and** label regex | **File is 168 lines.** phone shape at **:140** (`len(sub >= 10)`), phone label regex at **:151**, `infer_shape` at **154-159**, not 178-197 | ❌ lines |
| `screen_review.py` `_MARKETING` ~28; applied 178; only in attestation branch | 28-30; applied at 178 inside `purpose=="attestation"` branch; non-required marketing → flag 181 | ✅ |
| `screen_review.py` map_screen 157-222 | 153-215 | ⚠️ minor |
| `screen_review.py:100` `_coerce_option` numeric "never for a dial code like +91" | exact: `if len(vnums)==1 and not v.startswith("+")` 100-101 | ✅ (crucial later) |
| `judgment.py` still_need ~238; matcher 85-110; 192-206 profile-only prompt | still_need escape at 238 ✓; `match_value_to_option` 85-110 ✓; 192-205 are the *call sites* (prompts 63-68 / 147-152); neither sees `ctx.job` | ✅ |
| `top_down.py` did-not-take 90-97 | exactly 90-97 (empty-after → `needs.append` 94-96, stdout-only 97) | ✅ |
| new fields re-asked 120-126 | 119-126 (`fresh → answer_fn`) | ✅ |
| `qa_recorder.py:67-76` answered→promote; `qbank_promote.py:26-44` guards | `answered()` 67-76 calls `promote_answer`; guards: `_COMPANY_SPECIFIC` 19-23, file/blank 31, sensitive 33-35 | ✅ |
| `autonomy.py` STABLE_SOURCES :22; record_submission 96-113; THRESHOLD :33 | **path is `src/job_dashboard/autonomy.py`** (not orchestrator). STABLE_SOURCES :22 ✅. `record_submission` is **86-111** (approvals +1 at 100-101). `AUTONOMY_THRESHOLD` is **:20** | ⚠️ path/lines |
| `boards/run.py` `_untick` 122-137 | exactly 122-137; note it matches only *non-required* boxes (`:not([required])` locator :129) | ✅ |
| C's fallback: "submit bounce re-asks the field (boards/run.py:405-418 retry built)" | retry exists (402-418, once, `retried_bounce`) but re-asks only **undecided `optional`** fields (410-414). A field C already declined+filled is NOT in `optional` → run stops `validation_error`. **As stated, false** | ❌ |
| B: tracker `save_as=once` default stores no entry | `job_dashboard/api/qa_routes.py` — default `"once"` :49, once branch no-op :211-219 | ✅ |
| `triage` DB evidence 30901/30604 | qa rows match verbatim (`shortlist referral_source 0.94 source qbank 'Job Board'`; `exact country_phone_code 1.0 qbank_likely '+91'`); 30604 = **0** application_qa rows | ✅ |
| "98 entries", approvals all 0; `answer_lesson` dead | approvals sum = **0** ✅, but **119 entries**, not 98. `answer_lesson` table exists in DB, **zero** code readers (grep) — dead ✅ | ⚠️ count |
| `Apply/queue_runner.py:86` argv | def at **:136-137** | ⚠️ line |
| D: "watchdog already avail: `apply/submit_watch.py`/`stall.watch`" | `job_dashboard/apply/submit_watch.py` **exists** (SubmitWatcher, `on_requeue` app.py:94-95) but lives in the **dashboard** process — re-queues whole runs, does **not** broker mid-run Telegram replies. **No `stall.watch` module found** (grep). `src/career_agent/apply/` directory doesn't exist | ❌ half |
| `filler.py:70-136` one-attempt combobox; 247-option comment | `_pick_combobox` 70-133, docstring "One attempt" 71; the 247-option phone-list comment is at **86-88** | ⚠️/❌ lines |
| `collector.py` numbered options 125-137; free-text ask 192-198; `_COMPANY_Q_RE` 21-27 | exact | ✅ |
| `escalation.py:19-31` JD 3800 | 19-31; `_JD_CHARS=3800` :14 | ✅ |
| `graph.py` fill_node 309-427; human-gate record 442-446 | exact (442-446: `apply_answers` → `record_answers`) | ✅ |
| `qbank.py:106` exact; embed 168-178 | exact :106-110 ✓; `default_embed` 171-178 | ✅ |
| `qa_store.py:117` prior_answers | exact | ✅ |
| `qbank_admin.py:32-65` calibrate | 32-66 | ✅ |
| `qbank_compose` MIN/UNMATCHED 0.40/0.50 (:20-22); compose prompt no-JD (:92-114) | exact — prompt has question+facts+today only | ✅ |
| `ats_promote` folds only `trail:` blocks | 65-68: blocks without trail kept. `escalated_fields` lines never machine-consumed | ✅ |
| TL;DR "30901 source exact/confident" | DB says `retrieval_kind=shortlist` (0.94, source qbank) — internally inconsistent with §2.1 which is correct | ⚠️ TL;DR |
| "qbank_option_map / golden pairs already exist to test A" | No per-site vocab anywhere (30901 rows have `options_json ''`); A's golden corpus is **empty until B fills it** | ❌ implied |

External probe findings the brief missed:
- `qbank_admin.py:72-73` **RETIRE already lists** `whatsapp_ok`, `sms_consent` — the codebase's own maintenance deliberately throws marketing consent entries away. Strongest existing-code argument **for** C.
- `qbank_memory.py:83-90` documents a deliberate invariant: *"A REQUIRED box cannot be declined: leave it to the rule mapper … never untick it."* C's required-checkbox decline **overrides a commented invariant** and gets no review.
- `answering.py` `record_answers` docstring (:164-166) says bank joins only "when promoted on the dashboard," but `qa.answered` → `promote_answer` **does** auto-insert when `promote_embed` is set (apply.py:318; qa_recorder.py:69-74). Docstring stale; B's premise "tracker replies don't promote" is right, but "Telegram replies promote" is *already true in-process*.

---

## 2. Per-candidate attacks

### Candidate A — Vocabulary Bridge

**A-1. Its normalizer re-enables a bug `_coerce_option` was explicitly written to prevent.** `screen_review.py:100-101` refuses numeric-range matching when the value starts with `"+"` — comment: *"never for a dial code like +91."* A's ladder "strip `+`/parens → numeric-only dial-map" strips the `+` **first**, then numeric containment is live: `+91` against Workday's 247-option dial list (filler.py:86-88) can band-match any option parsing to number 91, or `91` → the *first* country whose option contains digit 91. Evidence the failure class is real: 30901 entered as a select with empty options and died in the raw-type fallback (`qbank_match.py:196-197`, filler.py:127-131 Escape). A's fix charitably resurrects the M-1-class bug inside a new table.
**A-2. Poisoned per-site map after one review.** The reconciler's LLM rung asks "which page option means the same *sourcing event*" (judgment.py:85-110 reused). Concrete: bank holds `referral_source = 'Job Board'`; a Workday select offers `LinkedIn / Indeed / Google / Naukri.com / Job Aggregator / Other`. The LLM has no ground truth about *where this job actually came from* and binds `Job Board → Naukri.com` (the only "portal-ish" label). One accepted fill (A's "gate new rows behind one review/submit") writes `qbank_option_map(site, referral_source, Naukri.com)`; every later Workday application on that ATS reports sourcing *Naukri* even when the click came from LinkedIn — recruiter-visible marketing data, silently wrong forever. Nothing in A double-checks against the click origin (the run's entry URL/board is never compared to the chosen `source` option).
**A-3 (bonus). Architectural mismatch understated:** "suspend `phone` shape when `has_dial_field(fields)`" can't be done in `infer_shape` — `answer_field(conn, f, …)` (qbank_match.py:279) sees *one* field, and `has_dial_field` needs the whole form (answering.py:52-55, applied in `answer_fields` :150-154). Threading form context into the bank lane (or moving dial-shaping out to the `answer_fields` layer) is real work beyond "add `dial_code` shape"; ~3-5d estimate is optimistic by a day or two.
**Testability cross-check:** test style is perfect for it (pure functions, `qbank_conn`/`fake_embed` fixtures — tests/career_agent/test_qbank_match.py) **but the promised golden set is empty** — no stored (entry, site-option) pairs exist today (`options_json ''` on both 30901 rows). `calibrate_vocab` has nothing to calibrate until B or live captures populate the table.

### Candidate B — Closed feedback loop

**B-1. Standing answers for company-named / eligibility questions.** `promote_answer` filters only why-questions, files, sensitive (_COMPANY_SPECIFIC qbank_promote.py:19-23, sensitive :33-35). Concrete chain: human answers Telegram "Have you previously worked for MKS Inc?" → "No" auto-promoted as a *standing* bank entry. Next run: "Have you previously worked for Google?" — MiniLM scores company-variable wording ≈ identical; ≥ HIGH 0.87 with margin (qbank_match.py:150-151) → **CONFIDENT**, no LLM, auto-fills "No" permanently and invisibly (this is exactly the "bank stays right only for exact repeats" hedge QBankMemory makes elsewhere — one-word company substitutions defeat it). Worse variant, and it's live **today**: Telegram "No" on a required `#phoneNumber--phoneType`-style question, or on "Are you legally authorized to work in …" — `authorized` is not in `_SENSITIVE_RE` (judgment.py:26-29) and not `_COMPANY_SPECIFIC` → the *pre-B* loop already promotes it; B's writer (a) "write-through even when mid-ask" and approvals bootstrap **amplify** the same hole and add auto-accept momentum.
**B-2. Approvals bootstrap rides a loose substring match.** "when human confirms a promoted entry's reply → approvals=1" is validated by `record_submission._same` (autonomy.py:78-83): `a == f or (a in f or f in a) and min(len) ≥ 3`. `"Job Board"` in a site's final `"Naukri.com (Job Board)"` → substring-true → **+1 approval earned on a value the site stored differently**; three such inflations = that answer is AUTONOMOUS (autonomy.py:70-71) and can go out with no human. B ships without tightening `_same` and thereby poisons the reward signal it's trying to warm up.
**B-3 (interaction).** With C later in the stack, the same marketing field now has two writers racing: C emits a decline-class decision while B's write-through candidate registry records the human's (blocked) telegram reply that no longer exists — B's curate shows phantom `pending` rows. Needs an explicit rule: candidates never recorded for fields a gate already decided.
**Testability:** strongest of the four — writers are pure (test_qbank_promote.py / test_qa_recorder.py conventions extend directly), transcript replay trivially writable.
**Effort:** schema+writers 2-3d realistic; *dashboard card* means FastAPI route + UI work (api/qa_routes.py precedent) — 2d is tight; approvals bootstrap is unusable without the `_same` fix (+1d). Total ~6d vs claimed 5.

### Candidate C — Decline-classifier gate

**C-1. Regex over-reach on required consent-to-be-contacted.** C's proposed `notif|get (updates|notifications)|notify (me|you)` catches real application questions. Concrete: Gulf/Workday forms ask *"Please notify me of the status of my application via email / SMS — required for eligibility to be considered"* — matches `notify (me|you)`; gate answers "No"/declines a box that recruiters treat as consent-to-contact; the candidate silently stops being shortlisted, and no submit bounce follows (the form *validates*). Similarly *"Any updates on your availability?"* matches `updates? \babout|on\b`. The mitigation "check the QA trail" only helps after the damage is repeated across runs, because a decline-class fill is auto and source `decline_class` never lands in Telegram review.
**C-2. It tramples a documented invariant and then punishes autonomy.** qbank_memory.py:83-90 explicitly refuses to decline a required checkbox ("never untick it"); C overrides that with `FillDecision("No", source="decline_class")`. And `"decline_class"` is neither in `STABLE_SOURCES` (autonomy.py:22) nor `qbank`, so `autonomy_report` emits *"decline_class: not a confirmed answer"* (autonomy.py:145-146) **forever** for every auto-declined field — any form carrying one declined marketing checkbox can *never* be autonomous. This coupling is unmentioned: C must add `decline_class` to STABLE_SOURCES or gate it as a blocker-exempt source, or it silently kills graduated autonomy.
**C-3 (safety net false):** the promised bounce re-ask doesn't exist for declined fields (see §1, boards/run.py:405-418 re-asks only undecided `optional`).
**Testability:** best in show — pure regex+shape; and the repo *already contains the negative-fixture*: `tests/career_agent/fixtures/consent_decline.html` and `consent_accept_only.html` (board tests). Unit tables + a board-route decline test are an afternoon.
**Effort:** 1.5d plausible for the classifier; +0.5d for the autonomy/STABLE_SOURCES surgery the brief omits. Realistically ~2.5d.

### Candidate D — Answer-policy contract

**D-1. The contract can mint false positive verdicts — read-back blindness.** `fill_top_down` treats `after is None` as success: `if after is not None and not str(after).strip()` else → `applied` (top_down.py:90-99). A shadow-DOM combobox (SR `spl-*` — filler.py:20-60 exists precisely because read-back/fill is hard there) that can't be read back gets verdict `bank_heuristic|judgment_options`, validator "non-null at end" **passes**, and the field may still be visually empty → submit bounces. The enum lacks a `readback_unverifiable` verdict; without it D's guarantee is only "something was decided", not what actually happened. The brief never tests read-back coverage, which is the *input* to every verdict.
**D-2. Telegram persistence is not a "2 day" bolt-on.** `TelegramCollector._await` is an in-process `client.poll_text` loop (collector.py:57-66); replies die with the child. Persisting them means an outbox/dashboard-side message queue plus reply-ID↔run_key binding, and the watchdog that could drive it (`job_dashboard/apply/submit_watch.py`) runs in the *dashboard* process and re-queues whole runs (app.py:94-95, queue_runner.py:22) — it cannot drain a live socket for a collector the agent child owns. "stall.watch" doesn't exist in this repo. Realistic cost: 4-5d, not 2; this is where D's ~3d (+2) estimate is most wrong.
**D-3 (interactions).** Verdict column vs `qa.decision()` status semantics (qa_recorder.py:45-52 `needs_answer` for `qbank_likely`) will double-encode state unless the recorder is the single writer — a refactor of every answering path (graph fill_node :331, boards `_answers` :282-296, judge-retry apply.py:60-67). With C, `decline_class` verdicts collide with autonomy as in C-2. With A, A's new sources must register verdicts or the enum check (QARecorder `decision()`) fails the run loudly — good discipline, but it ties D's rollout to A/B shipping.
**Testability:** validator-as-test works; the enforcement point `QARecorder.decision` is already unit-tested (test_qa_recorder.py) so asserting verdict columns per source is natural. The histogram/replay tests are writable.

---

## 3. Interaction matrix (the ones that matter)

| Pair | Conflict | Resolution the builders must spec |
|---|---|---|
| C ↔ autonomy | `decline_class` not in `STABLE_SOURCES` (autonomy.py:22,145-146) → forms with declines never autonomous | register source or exempt declines from blockers |
| C ↔ boards bounce | bounced declined fields are not re-asked (boards/run.py:410-414 only `optional`) | keep declined fields *undecided* until submit passes, or add re-ask on bounce |
| C ↔ qbank_memory invariant | required checkbox declines violate qbank_memory.py:83-90 comment | decide policy-level: replace comment + add required-decline to review trail |
| B ↔ autonomy | approvals bootstrap + `_same` substring match (autonomy.py:78-83) inflate approvals on container strings | tighten `_same` (exact-normalized) *before* bootstrapping |
| B ↔ B(promote) | company-named / authorization answers promoted standing (qbank_promote.py guard gap) | extend `_COMPANY_SPECIFIC` or require non-empty `label_options`+value-fits rule for auto-accept |
| B ↔ A | A's golden tests need B's `qbank_option_map` corpus; A should be built *reading* B's table, not in parallel | B's curate "accept as wording" writes option lists → feeds A (brief already says this; order matters) |
| A ↔ `_coerce_option` guard | A's `+` stripping bypasses the dial-code numeric guard (screen_review.py:100-101) | normalization must happen *inside* the guard, dial-map only over `_DIAL_OPTION`-matching options |
| D ↔ A/B/C | verdict enum must register every new source at QARecorder.decision | enum check + one registration line per candidate |
| D ↔ read-back | `after is None` misses unverifiable fills (top_down.py:90) | add `readback_unverifiable` verdict or fix `_value` fallbacks first |

---

## 4. Scored comparison

(5 = best; poisoning/loop scored 5 = lowest risk)

| Criterion | A vocab-bridge | B feedback loop | C decline gate | D policy contract |
|---|---|---|---|---|
| Reliability of fix | 3 — two-stage matching is sound, but LLM semantic binding has no ground truth to check against | 4 — writers are deterministic; risk is only in *what* gets accepted | 5 — pure regex, deterministic, and its inputs (label+kind+required) are already on the field | 4 — observability is reliable if D-1's readback hole is closed first |
| Generality | 4 — helps every value-mismatch class (dial, currency, taxonomy) per site | 4 — grows bank for *all* future asks, any class | 2 — one class (marketing/notifications) only | 5 — meta-level; serves A/B/C metrics and the crash case |
| Poisoning/loop risk | 2 — wrong per-site maps look self-confirming; `+`-strip undermines an explicit guard | 2 — standing answers for company/eligibility wording; `_same`-substring approval inflation | 4 — over-decline possible but visible in QA and cheap to patch | 3 — verdict drift possible; false-applied fills can be *recorded* as good |
| Testability | 3 — perfect fixture style, but golden corpus is empty until B | 5 — pure writers, transcript replays, existing promote tests | 5 — consent_decline.html fixture already exists; table tests trivial | 4 — validator-tests itself; verdict recording testable in QARecorder style |
| Effort realism | 2 — headlined 3-5d; form-context threading + collector plumbing for live-option asks push it to ~6-7d | 4 — ~6d realistic vs 5 claimed (dashboard card tightens) | 5 — ~2.5d realistic vs 1.5 claimed | 2 — telegram persistence alone is 4-5d (wrong module cited); verdicts ~3d ok |

(Sums: C 21 > B 18 > D 18(=16 by raw but D-1 gates reliability) > A 14.)

## 5. Verdict — recommended build order

The brief's C→B→A (+D folded) is **directionally right but mis-ordered at the middle**: it slots A second, and A is the least-match-*ready* candidate (empty golden corpus, guard-bypassing normalizer, form-context threading) and the only one that writes recruiter-visible data automatically. I'd build:

1. **C (decline gate), with two corrections C's author must absorb:** (a) register `decline_class` in `STABLE_SOURCES` / autonomy exceptions (autonomy.py:22,145-146); (b) required-checkbox declines keep the field **undecided** (flagged in QA, re-asked on the boards bounce path) instead of stuffing "No", preserving the qbank_memory.py:83-90 invariant — only *optional* marketing gets an affirmative decline decision. Tighten the regex against `notify (me|you)`/`updates? (about|on|from)` with a required-vs-informational split.
2. **B (feedback loop) minus approvals bootstrap:** writers + candidate registry + curate CLI first (the tracker-replay is where the 1077 `needs_answer` backlog converts into entries); **defer the approvals=1 bootstrap until `_same` (autonomy.py:78-83) is tightened and the company-named/eligibility promote guard (qbank_promote.py) is extended** — otherwise the loop teaches itself falsehoods at machine speed.
3. **A's dial/vocab reconciliation, built *on* B's table:** start with the deterministic half only — dial-code shaping at the `answer_fields` layer (answering.py:150-154, where page context already exists) plus the fail-forward "reduced ask" — and gate the LLM semantic rung behind the option-map rows B produces from real accepted answers. Never strip `+` before `_coerce_option` (screen_review.py:100-101).
4. **D-lite through everything, full D last:** the `policy_verdict`/`decisions.jsonl` journal + validator is cheap and belongs in C's QA recording from day 1 (fold D's coverage of `unresolved_filler_failed` into top_down.py:90-97). The Telegram persistence half is genuinely a +4-5d, dashboard-queue effort (submit_watch.py re-queues runs; it cannot mid-ask-broker replies) — schedule it after A, not alongside B.

**One-line rationale:** C and B's deterministic halves remove ~all of the observed waste (30604 ask, lost learning) at near-zero risk; A's value is real but it should *consume* B's verified vocabulary rather than guess it; D's observability is worth having immediately while its crash-durability is the most expensive-to-do-right piece in the stack.
