# Navigation fix — DECLARATIVE school (competitor design)

Fixes failure classes A–E (reach-the-form failures) **primarily by editing
`docs/career-agent/ats-graph.json` and adding one generic interpreter per
incoming data type**. No per-site code branches. Target diff in `.py`: ~110
lines total across 4 files (details §2).

Baseline evidence cited per class; all five are reach failures, not fill/submit
failures.

- **A — Indeed external-apply link missed.** `board:indeed` entry is a single
  selector `#indeedApplyButton, button:has-text("Apply now"), a:has-text("Apply now")`
  (docs/career-agent/ats-graph.json:762-765). External jobs (30285/30833) expose
  "Apply on company site" instead → entry click throws → `no_entry`
  (data/agent_runs/30285/board_run.json:1). The `left_board` handover itself
  already works: run.py:391-392 stops, and apply.py:456-464 re-classifies and
  hands the career-site engine the off-board page (data/backups/agent_runs-eval-20261013-012631/30833/board_run.json
  step 1 = left_board → peoplestrong).
  The runner side is fine too — `job_target` prefers `apply_kind=external` +
  `apply_url` (src/job_dashboard/apply/queue_runner.py:36-40) — but the Indeed
  scraper always writes `apply_url=None, apply_kind="native" | "external"`
  (src/job_dashboard/sources/cdp/indeed.py:66), so the target is always the
  listing URL and only the board entry chain can escape.
- **B — Himalayas upsell modal retried 6×.** Job 31867: modal "Don't let your
  application get lost in the pile", agent clicked "Apply now" then "I'm ready
  to apply", re-hopped, modal returned, repeated, `reach_end: none` twice, six
  `modal_kept (offers an apply control)` trailing entries
  (data/pending_memory_updates.md:1367-1374, 1397-1404, 1430-1437). No
  arbitration data: which modal button wins and a reopen cap. The phrase-priority
  layer knows the button (`"i'm ready to apply"` is rank-0 in `_APPLY_ALLOW`,
  src/career_agent/browser/page_prep.py:406-411) but nothing records
  (a) this modal copy, (b) its preferred button, (c) "second reopen = stop".
- **C — Himalayas ad-iframe fake "Apply Now" clicked.** Job 31505: repeated
  `hop click 'Apply now' (frame 0)` then the native modal returns/`Close`
  (data/pending_memory_updates.md:1228-1345). Frame-level denial exists
  (`find_apply_affordance` skips frames matching `_frame_is_ad`,
  page_prep.py:551-553 + 564-571; `collect_raw` uses `is_denied_frame`,
  src/career_agent/browser/perception.py:663-690) but the deny list is a
  hard-coded tuple of ad networks (`_AD_HOSTS`, page_prep.py:421-430) and
  `_real_field_count` sums **all** frames with no ad-filter
  (page_prep.py:471-478) — a site-specific deny list has no home in the graph.
- **D — POST-replay chrome-error page.** Job 29987 Deloitte: after Login click
  the tab landed `chromewebdata/`, `reach_end none` twice, claude_assist
  invalid (data/pending_memory_updates.md:1440-1447). A fresh GET of the same
  URL works live. Nothing in graph or code recognizes an ERR_* / chrome-error
  navigation artifact or recovers by replaying the GET.
- **E — Instahyre signup wall perceived as fields.** The board engine already
  stops `logged_out` on the register redirect thanks to
  `logged_out: ["/login/", "/candidates/register"]` (ats-graph.json:836-839)
  consumed by `is_logged_out` (src/career_agent/boards/signals.py:26-27,
  checked in `_blocked`, src/career_agent/boards/run.py:72-73;
  data/agent_runs/30076/board_run.json:1 proves it). Residual risk is the
  engine-level perception: `classify_entry` returns "form" whenever ≥2 visible
  fillables exist (page_prep.py:227-228, 481-484) and `login_from_signals`
  caps at ≤4 cred inputs so a long register page escapes the wall detector
  (page_prep.py:252-256) — e.g. the left_board handover path (apply.py:456-464)
  re-classifies a wall page as a form.

---

## 1. What goes into ats-graph.json (data only)

### 1.1 Board entry CHAIN with ordered fallbacks + external handoff (fixes A)

Extend the `entry` object of `board:*` nodes from a single selector to an
ordered chain. Legacy `entry.selector` remains the chain's first leg so
nothing is rewritten:

```json
"board:indeed": {
  "entry": {
    "selector": "#indeedApplyButton, button:has-text(\"Apply now\"), a:has-text(\"Apply now\")",
    "submits": "no",
    "chain": [
      {"selector": "#indeedApplyButton", "leg": "native"},
      {"selector": "button:has-text(\"Apply now\"), a:has-text(\"Apply now\")", "leg": "native"},
      {"selector": "[aria-label*='company site' i], a:has-text('Apply on company site'), button:has-text('Apply on company site'), a:has-text(\"Apply to the employer's site\")", "leg": "external", "handoff": "external"}
    ]
  }
}
```

Semantics: try legs in order; the first leg that clicks wins. A leg marked
`handoff: "external"` tells the engine the outcome is expected to be
a `left_board` (run.py:392) stop → the career-site engine continues
(apply.py:456-464, already implemented). `on_board` (profiles.py:48-52)
remains the post-click oracle. The chain is data, so SmartApply pages simply
consume leg 1, and external pages consume leg 3 instead of stalling at
`no_entry`.

### 1.2 Per-site modal tells with preferred button + reopen cap (fixes B)

New optional `modals` array on **site** nodes (site:himalayas,
ats-graph.json:920-946, is the first consumer), interpreted alongside the
board's `interstitial` list (boards/run.py:140-148):

```json
"modals": [
  {"tell": "don't let your application get lost in the pile",
   "prefer": ["I'm ready to apply", "Apply now"],
   "close": ["Close", "X"],
   "reopen_cap": 2,
   "on_repeat": "stop:modal_loop"}
]
```

Arbitration model, all declarative:
- `tell` matches the modal heading text → this rule owns the modal;
- `prefer` gives the ordered button labels to press (codes never choose);
- `reopen_cap` bounds identical reopens — beyond it, stop with
  `modal_loop` instead of the 6× identical snapshot retries seen at
  pending_memory_updates.md:1374;
- A second rule on the same site can deny the AI-upsell CTA
  (`{"tell": "generate cover letter with ai", "prefer": ["Not right now"]}`)
  to mirror strategy:chatbot_deny's "prefer real Apply" intent
  (ats-graph.json:114-119).

### 1.3 Site frame-deny + preferred control (fixes C)

Two optional site fields, consumed by existing generic code paths:

```json
"deny_frame_hosts": ["carbonads.com", "buyads.com", "ad.doubleclick.net", "feeds.feedburner.com"],
"preferred_apply": [{"name": "Apply now", "scope": "sticky_bar|main"}]
```

- `deny_frame_hosts` extends `_AD_HOSTS` (page_prep.py:421-430) per-site for
  both the affordance scan (`find_apply_affordance`, :551-553) and perception
  (`collect_raw`, perception.py:663-690).
- `preferred_apply` a per-site `prefer` seed for `_best_apply`
  (page_prep.py:446-462): exact learned/preferred names outrank allow-phrase
  rank. When the correct and the fake control share the name
  ("Apply now" ×2 at 31505), `preferred_apply` may carry an optional
  `locator` (CSS anchor, e.g. the sticky bar container) that `_hop`
  (page_prep.py:574-610) tries before name-only matching.

### 1.4 chrome-error recovery rule (fixes D), archetype-level

New top-level `rules` array (any engine honors them, not just boards):

```json
"rules": [
  {"id": "rule:chrome_error_replay",
   "when": {"page_match": "chrome-error://|about:blank", "title_match": "^ERR_", "title_match2": "ERR_CACHE_MISS|ERR_EMPTY_RESPONSE"},
   "then": {"goto": "job_url", "fresh": true, "max_replays": 1},
   "status": "current"}
]
```

One generic hook reads `rules` and replays the original URL once when the tab
is sitting on a chrome error artifact (trail at pending_memory_updates.md:1446:
`landed: chromewebdata/`). A second failure becomes `site_refused`. It meshes
with the existing `archetype:account_wall → strategy:handoff` chain
(ats-graph.json:55-61, 1287-1290) — recovery happens *before* wall checks.

### 1.5 Signup-wall URL tells (fixes E), engine-level

Two zero-new-schema additions:
- `board:instahyre.logged_out` (ats-graph.json:836-839) already carries
  `/candidates/register` — keep, add `"create your profile"` and
  `"candidates/register"` variants.
- New site/archetype field `signup_wall_tells` (URL regexes) attached to
  `archetype:account_wall` (ats-graph.json:55-61) — "any /register,
  /signup, /candidates/register redirect from an Apply click is the account
  wall, not a form", consumed by the engine the same way `board.logged_out`
  is (run.py:72-73) and returned as `password` by `_reach`
  (page_prep.py:652-654 already hands walls to the caller) so the handoff
  path (apply.py:462) classifies correctly.

---

## 2. Minimal code changes (~110 lines diff total; no code shown, intent only)

1. **`src/career_agent/boards/profiles.py`** — `load_boards` (:28-34) and
   `_DEFAULTS` (:14-20):
   - add defaults `modals: []`, `chain` (absent = legacy selector only);
   - after building the board dict, merge the site-node fields
     (`deny_frame_hosts`, `preferred_apply`, `modals`) of hosts matched via
     the board's domains — one dict-union, ~12 lines. This keeps run.py
     board-centric while site data rides along.

2. **`src/career_agent/boards/run.py`** — `run_board` (:299), entry block
   (:349-364), `_interstitials` (:140-148), `_blocked` (:62-74):
   - **`_entry_chain(page, board)`** (~15 lines): returns the ordered legs
     (`chain` or the legacy single selector as one leg). Modify the entry
     click to iterate legs — click; on success break; record `res["entry"] =
     {"leg": i, "handoff": bool}` for the run log; a `handoff:"external"` leg
     that lands off-board follows the *existing* `left_board` stop (:391-392)
     with no new semantics; list exhaustion keeps today's
     `no_entry`/assist.recover (:362-364).
   - **`_modal_tells(page, board, seen)`** (~20 lines): for each `modals`
     rule, if a visible dialog's text matches `tell`: click the first
     `prefer` control (via the same covered-control evaluate fallback as the
     entry click, :354-358); track tells→press count in a session dict;
     exceed `reopen_cap` → `stop("modal_loop")`. Called once next to
     `_interstitials` (:368) and once per loop iteration next to `_blocked`
     (:388-390).
   - **`_error_recovery(page, board, job_url)`** (~10 lines): new graph
     rules lookup + replay — on `chrome-error|about:` URL or `^ERR_` title →
     single `page.goto(job_url, fresh)`; wired at loop-top with `_blocked`
     so both board and non-board paths honor `rule:chrome_error_replay`.

3. **`src/career_agent/browser/page_prep.py`** (~25 lines):
   - **`_frame_is_ad`** (:564-571) / `_is_ad_frame` (:425-430): union the
     site-node `deny_frame_hosts` (memoized 3-line graph read, like the
     existing `_GRAPH` reads in boards/profiles.py:12) into the deny test.
   - **`_known_clicks`** (:613-625): also return the site's
     `preferred_apply` entries (name + optional `locator`); `_best_apply`
     (:446-462) already prefers exact learned names (rank < 0,
     :458-462), and `_hop` (:574-610) gains one branch: if the chosen
     affordance carries a locator, try `clicker.locator(locator)` before the
     name locator.
   - **`_reach`** (:634-698): before the `is_application_form` verdict
     (:655), consult signup-wall tells (board `logged_out` via
     boards.profiles.board_for + signals.is_logged_out — reuse, no new
     parser): a wall URL returns `(active, "password")` for the caller's
     standard escalation, instead of letting `_real_field_count`
     (:471-478) bless a register page as a form (~8 lines).

4. **`src/career_agent/memory/ats_promote.py`** (~25 lines, §3):
   - on successful runs whose last hop produced a `left_board`
     (`reach_end` status `off_board`/host change): append that click name to
     the board's `entry.chain` as a new `{"leg": "external", "handoff":
     "external"}` leg (dedupe by selector name, cap 2 learned legs,
     `learned: true` stamp, ordered *after* declared legs).
   - on runs whose trail shows `intercept "modal: X"` followed by a
     successful hop: write/refresh the matching `modals[].prefer` entry for
     that site; on runs that stopped `modal_loop`, demote the pressed button
     one rank instead of re-promoting.

Unchanged on purpose: drivers (drivers.py FormDriver/ChatDriver :55-177),
confirm/logged_out/challenge signal matching (signals.py:17-70), the
left_board → career-site handover (apply.py:456-464), and
`_run_board`'s limiter (apply.py:775-797).

---

## 3. How ats_promote grows the chains automatically

The loop already exists end to end:
1. `queue_runner.drain` folds trails after every job
   (src/job_dashboard/apply/queue_runner.py:94, :110, :131 → `_promote_trails`
   :82-89 → ats_promote.promote()).
2. `promote` groups blocks by entry host, keeps only *successful*
   (`stopped_reason == "None"`) paths as `reach_path` / `reach_clicks`, and
   adds `ROUTES_TO` edges to the landing host (ats_promote.py:84-97; node
   creation via `_site` :31-36).
3. `site_hint` serves those nodes back (src/career_agent/browser/ats_lookup.py:92-103)
   to `_known_clicks` (page_prep.py:613-625), whose names feed `_best_apply`
   as the `prefer` list (page_prep.py:458-462) — exact learned names outrank
   every generic phrase.

So the declarative extension is the *same* loop pointed at the two new
fields (§2.4):
- **Entry chains self-serve:** a site whose first external "Apply on company
  site" escape ever succeeded gets that click written into
  `entry.chain` as the external leg; next Indeed/himalayas-style job consumes
  the learned leg without a human edit. When a run later proves the learned
  leg dead (`no_entry` twice with `entry.leg = learned`), `promote` flips it
  to `status: superseded` — the graph's established deprecation convention
  (ats-graph.json:4 note + SUPERSEDES edges, e.g. code:learned_answers :908-912).
- **Modal preferences self-serve:** each run that enters a modal and then
  makes forward progress contributes (tell, pressed-button) evidence;
  majority-evidence (seen twice) is required before `prefer` is written, so a
  single A/B copy variant cannot corrupt the rule; `modal_loop` verdicts
  demote.
- **Recovery rules never self-serve:** `rule:chrome_error_replay` is
  archetype-level and hand-written only — a mis-learned replay loop is the
  dangerous case, so it stays declared, not learned.

Cost guardrails all inherited, no new knobs: promotion is deterministic, no
LLM (ats_promote.py:1-8); graph write is the same `json.dumps(indent=2)` flush
(:98-102); the queue never breaks on promote errors (:86-89).

---

## 4. Edge cases, failure modes, and where code-only wins

- **Learned-entry flukes and drift.** A once-successful external click can be
  wrong later (posting gains native SmartApply again; site A/B renames
  buttons). Mitigations: declared legs always outrank learned legs; two-strike
  demotion; `entry.leg` recorded in results so the tracker shows which leg
  fired. *Remaining risk*: silent selector rot — a chain leg that never
  matches produces no error, only a costlier fallthrough to later legs.
- **Modal heuristics under copy churn.** `tell` phrases are brittle to
  re-wording; `prefer` may pick an upsell CTA if the copy resembles a
  neutral tell. `reopen_cap` bounds the damage to one stop per run, but the
  run still fails once until evidence re-accumulates.
- **`modal_loop` vs. genuine re-render.** A modal that legitimately
  re-appears after each step (unchanged copy!) could trip the cap. Anchor the
  cap on (tell + press count), not on (modal visible count).
- **chrome-error rule can mask real dead pages.** Only replay when
  `is_closed_posting` (page_prep.py:178-182) says the *fetched* page is not
  closed, and `max_replays: 1` — a server that 500s twice is `site_refused`,
  never a replay loop.
- **Ad-deny lists lag reality.** Graph-sourced `deny_frame_hosts` still
  cannot catch a top-document ad slot with no child frame (e.g. a promoted
  "Related jobs" card rendering its own Apply). That needs a runtime
  structural check.
- **What the declarative school cannot fix — code-only wins:**
  1. **Fill-time arbitration inside dynamically-mounted DOM.** Selector
     strings cannot express "the real Apply is the one my runtime stamped
     `data-aff` and which sits in a sticky bar" reliably across widget
     variants; `_CLICKABLES_JS` stamping + in-modal-first sorting
     (page_prep.py:321-341) is a code-level behavior that data can only
     *prefer among*, not replicate.
  2. **Cross-origin iframe perception/fill at run time** (`collect_raw`,
     perception.py:663-690; frame-qualified refs) — data can deny bad frames,
     but reaching *into* frames is code (`frame_target`,
     time-bound loads :680).
  3. **Challenges and OTP** — boundaries `no_captcha`/`no_account`
     (ats-graph.json:358-371) forbid solving; gate probing/handoff is code
     (gate_probe, live_view — graph code nodes :182-199).
  4. **POST-replay itself.** The `goto` request semantics (cache bypass,
     `wait_until`) are engine behavior; the graph only declares *when* to
     replay.
  5. **Perception truth ("26 perceivable fields" style overcounts).** Field
     counting heuristics (page_prep.py:276-315) and perception filters are
     code; declaring "this URL is a wall" only short-circuits the miscount —
     a wall *without* recognizable URL/pw signals still needs code.

---

## 5. Effort estimate and task breakdown (each ≤0.5 day)

| # | Task | Est |
|---|------|-----|
| T1 | ats-graph.json v3 edits: `entry.chain` for board:indeed (+ other one-click boards get trivial 2-leg chains), `modals`/`deny_frame_hosts`/`preferred_apply` on site:himalayas, `rules[]` chrome-error entry, instahyre tell additions + archetype `signup_wall_tells` | 0.5 d |
| T2 | boards/profiles.py: defaults + site-field merge into board dicts (+ unit test) | 0.5 d |
| T3 | boards/run.py: `_entry_chain` + entry-block loop + `entry.leg` in result (+ test with fake legs) | 0.5 d |
| T4 | boards/run.py: `_modal_tells` arbitration + reopen cap + `stop("modal_loop")` (+ test) | 0.5 d |
| T5 | page_prep.py: graph-frame deny union + `_hop` locator branch + `_reach` signup-wall return (+ tests for `_best_apply` prefer path) | 0.5 d |
| T6 | boards/run.py: `_error_recovery` hook honoring `rule:chrome_error_replay` (+ test: synthetic chrome-error URL) | 0.25 d |
| T7 | ats_promote.py: learned-chain legs + modal prefer/demote with majority rule; supersede flip (+ test on synthetic pending file) | 0.5 d |
| T8 | Regression probe: the five jobs (30285, 30833, 31867, 31505, 29987) + one clean job per board via `--probe`; verify `entry.leg`, modal evidence, no regression on naukri/linkedin/wellfound chain10 set (data/battle/chain10.jsonl) | 0.5 d |

**Total ≈ 3.25 eng-days** (~110 code lines + JSON). Sequencing: T1/T2 unblock
T3–T6; T7 optional-but-recommended before T8 so chains grow from the probe
runs themselves.

---

## Claims table

| failure class | fix element | file | lines changed (estimate) | risk |
|---|---|---|---|---|
| A | `entry.chain` with external `handoff` leg on board:indeed | docs/career-agent/ats-graph.json + src/career_agent/boards/profiles.py + src/career_agent/boards/run.py | 25 json / 12 py / 15 py | low — falls back to legacy selector; off-board path already proven (run.py:392, apply.py:456) |
| B | `modals[]` tell + `prefer` + `reopen_cap` on site:himalayas; `_modal_tells` interpreter + `modal_loop` stop | ats-graph.json + boards/run.py | 18 json / 20 py | medium — phrase `tell` churn; cap mis-trips if modal legitimately re-opens (anchor on tell+presses) |
| C | `deny_frame_hosts` + `preferred_apply` (name/locator) on site:himalayas; `_frame_is_ad` union; `_hop` locator branch | ats-graph.json + src/career_agent/browser/page_prep.py | 15 json / 25 py | medium — top-document ad slots without child frames still evade; structural runtime check is code-only |
| D | `rule:chrome_error_replay` in graph `rules[]`; `_error_recovery` single fresh GET at loop-top | ats-graph.json + boards/run.py | 12 json / 10 py | low — `max_replays:1` + not-closed guard prevents loops; masks nothing beyond one GET |
| E | instahyre `logged_out` additions + archetype `signup_wall_tells`; `_reach` wall short-circuit via board_for+is_logged_out | ats-graph.json + page_prep.py | 6 json / 8 py | low — reuses proven board tells (30076 logged_out proof); URL-less walls remain a code problem |
| self-serve | ats_promote writes learned `entry.chain` legs & `modals[].prefer` w/ majority + supersede | src/career_agent/memory/ats_promote.py | 25 py | medium — learned order flukes; bounded by declared-legs-first + two-strike demotion |
