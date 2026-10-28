# Failed-submission repair — tournament plan (2026-10-21)

Scope: every apply run since 2026-10-01 (377 runs). 68% reached review/dry-run; the rest
blocked pre-form or escalated answers. Everything below lives in the worktree
`failed-submissions-fix` — **no changes to `main`**. Evidence docs:

- `docs/career-agent/triage/failed-submissions-2026-10-21.md` (classifier agent)
- `docs/career-agent/triage/answer-pipeline-analysis.md` (architect agent)

## Verified failure classes (triage)

| # | class | evidence (verified live or from artifacts) | jobs (examples) |
|---|-------|-------------------------------------------|------------------|
| A | Indeed external-apply: entry selector misses "Apply on company site" | screenshot `30285/perceive0.png`; timeout on `#indeedApplyButton…` | 30285, 30833, 30430 |
| B | Modal arbitration missing | `31867/perceive1_6.png` upsell modal "I'm ready to apply", 6 identical retries | 31867, 30178? |
| C | Ad-decoy "Apply Now" (ad iframe) beats real sticky CTA | `31505/perceive0_6.png` fake ad w/ Apply Now, sticky bar ignored | 31505 |
| D | POST-replay error pages (ERR_CACHE_MISS → chrome-error) | `29987/perceive0.png`; fresh GET loads JobDetail fine w/ visible Apply | 29987 |
| E | Logged-out wall not pre-checked; signup form perceived as job fields | `30076/perceive0.png` signup wall, 26 "fields"; live: Apply→`/candidates/register/` | 30076, 30233, 30998 |
| F | Node helper EPIPE crash mid-ask; artifacts not flushed | `30604.log` lines 23–38; no board_run.json saved | 30604 |
| G | Bank-answerable questions escalated not matched / not filled | `30901.log` "How Did You Hear About Us*", "Country Phone Code*"; qbank HAS `referral_source`="Job Board", `country_phone_code`="+91" verbatim | 30901, 30604 |
| H | Policy stops working as designed (daily cap, judgment-src review, one-click) | 30925, 31870, 29839 | — (not bugs) |
| — | Observability gaps: null stopped_reason rows, retry screenshots without step pairing, assist dependent on Claude quota | run_log null rows; `[assist 1/5] weekly limit` in 30285/30833 | multiple |

## Candidate solution families (to compete)

Each family gets ≥2 competing designs scored on: reliability, generality,
blast-radius, observability, effort, testability. Winner per family is implemented
as a task in this worktree.

- N (navigation): N1 data-driven entry chains in ats-graph.json + handoff on
  external/left-board; N2 generic error-page & login-wall recovery engine;
  N3 CTA ranking heuristic (sticky/main-frame preference, ad-iframe exclusion).
- Q (answers): Q1 retrieval upgrade (normalization + variant matching + option
  reconciliation); Q2 deterministic decline/policy gate before human escalation;
  Q3 closed feedback loop (telegram/judge answers → qbank promotions); Q4 answer
  contract (every field must exit via bank|llm|decline|human with trace).
- O (observability): O1 run trace JSONL + step-paired screenshots; O2 never-lose-
  a-crash (flush board_run.json + handler for child-process EPIPE); O3 assist
  fallback when Claude quota hit.

## Competition results — answer family (red-team corrected, `answer-redteam.md`)

| candidate | reliability | generality | poisoning risk | testability | effort realism | verdict |
|---|---|---|---|---|---|---|
| C decline gate | 5 | 2 | 4 | **5** (consent fixtures already exist) | ~2.5d real | **1st** — but must (a) register `decline_class` in autonomy STABLE_SOURCES/exceptions (autonomy.py:22,145-146), (b) keep required-checkbox declines *undecided* + re-ask on bounce (preserves qbank_memory.py:83-90 invariant), (c) tighten `notify (me|you)` regex |
| B feedback loop | 4 | 4 | 2 (see guard gaps below) | 5 | ~6d real | **2nd, sans approvals bootstrap** — writers + `qbank_candidate` + `scripts/qbank.py curate` first; the tracker replay converts the 1077 `needs_answer` backlog. Defer approvals bootstrap until `_same` (autonomy.py:78-83) is exact-normalized and promote's company/eligibility guard (qbank_promote.py:19-23) is extended — else "Have you worked for MKS? No" becomes a *standing* answer that auto-fills Google at ≥0.87 confidence |
| A vocab bridge | 3 | 4 | 2 | 3 (golden corpus empty until B) | ~6-7d real | **last, built on B's table** — deterministic dial shaping at `answer_fields` layer only; never strip `+` before `_coerce_option` (screen_review.py:100-101); LLM semantic rung gated behind real `qbank_option_map` corpus |
| D policy contract | 4 | 5 | 3 | 4 | verdicts ~3d; telegram persistence 4-5d | **D-lite now, full D later**: `policy_verdict` + `trace.jsonl` folded into C's QA recording from day 1; add `readback_unverifiable` verdict (top_down.py:90 hole); full Telegram persistence is a dashboard-side queue job — after A |

Stack order: **C → B(writers) → A(on B) → D-lite⟩full-D**, with the verdict
columns shared via QARecorder as the single writer.

## FINAL WINNERS per family

| family | winner | mechanism |
|---|---|---|
| Navigation | **hybrid** (school-scoped per class) | A: declarative entry.chain (+4 employer-site label priors) · B: behavioral upsell dismiss + 2-strike degrade · C: behavioral cta_arbiter (ad-score+sticky) · D: behavioral page_health.py · E: behavioral URL-first wall gate |
| Answers | **C → B(writers) → A(late) as scored above** | decline gate frees humans from marketing asks; feedback loop turns every human answer into bank growth; vocab bridge reuses verified B corpus |
| Observability | **O1 → O2 → O4 → O3 → O5** | crash-durable trace is the spine; orphan reconciliation + assist ladder cheap; child-health after F proof |

## FINAL TASK DAG (worktree `failed-submissions-fix`; ~16 tasks, ≤0.5d each)

Nav: 1) entry.chain data+interpreter (A) · 2) cta_arbiter ad-score+position (C) ·
3) modal archetype chain + 2-strike degrade (B) · 4) page_health.py (D) ·
5) wallish_url gate + cred-provider into board ctx (E) · 6) nav regression probes
(30285/30833/31867/31505/29987/30076).
Answers: 7) decline-classifier gate + autonomy registration + undecided-required
policy (C) · 8) STABLE_SOURCES/exceptions test · 9) qbank_candidate schema+writers
(B) · 10) curate CLI + tracker-replay · 11) tighten `_same` + extend
`_COMPANY_SPECIFIC` guard (pre-req 12) · 12) deferred approvals bootstrap ·
13) dial shaping at answer_fields layer + reduced-ask fail-forward (A dets.) ·
14 vocab bridge LLM rung gated on B corpus (A) · 15) D-lite verdict columns +
trace.jsonl + validator.
Observability: 16) trace.jsonl+sidecars (O1) · 17) orphan/dead-ask + watcher
run_log rows (O2) · 18) assist quota ladder (O4) · 19) Node-child health + EPIPE
restart (O3) · 20) screenshot corpus sidecars (O5).

Validation bar: pytest `tests/career_agent` green; fixture replays of the 6 nav
jobs + transcript replays for B/C; `qbank.py calibrate` unchanged metrics.

## Competition results — navigation family (scored 1–5; see per-class verdicts)

Docs: `nav-design-DECLARATIVE.md`, `nav-design-BEHAVIORAL.md`,
`nav-design-OBSERVABILITY.md`.

| class | DECLARATIVE (data+interpreter) | BEHAVIORAL (generic code) | winner & why |
|---|---|---|---|
| A indeed external-apply | 5 — entry.chain leg + handoff rides the *proven* left_board path (30833 eval artifact shows handoff working already); ~52 changed lines | 3 — arbiter fixes it but ~150 new lines and must not mis-rank other boards | **declarative** (with the 4 employer-site label priors folded into `_APPLY_ALLOW` as a one-line insurance) |
| B modal loop | 3 — per-site modals[] data is right shape but nothing protects a site whose data is missing/stale | 5 — archetype chain + mandatory 2-identical-snapshot degrade protects *every* site; degrade after 2, not 6 | **behavioral**, with declarative modals[] as optional data (skip v1) |
| C ad-decoy CTA | 2 — static deny_frame_hosts lags rotating ad hosts; top-doc ad slots admit it themselves | 5 — ad-score (host+DOM+position) + sticky-bar feature is runtime truth | **behavioral** |
| D chrome-error | 4 — graphs rule[] + 10-line hook; fine | 5 — page_health.py is universal, ERR_* syndromes are not site-specific; no data churn | **behavioral** (declarative rules[] skipped) |
| E login wall | 3 — needs a code gap closed anyway (handoff re-blessing register page) | 5 — URL-first wall gate (≥2 corroborating tells) before perception + cred-provider wiring into board ctx | **behavioral** |

Net: **hybrid** — one declarative slice (A) + four generic slices (B–E); the schools
disagree least where it matters: both keep boards/domains/caps data-centric.

Answer family pending the red-team verdict (`answer-redteam.md`).</think>Now the verdict matrix is drafting well. Awaiting the red-team on the answer family — meanwhile everything else is scored.<tool_call>execute<arg_key>code</arg_key><arg_value>// Check worktree doc inventory while waiting
const { execSync } = undefined; // no fs access in execute
return "use shell instead";
