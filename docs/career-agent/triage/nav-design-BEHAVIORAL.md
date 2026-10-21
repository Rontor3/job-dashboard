# nav-design-BEHAVIORAL — generic reach-the-form, modal, page-health, wall detectors

School: **behavioral / generic**. Thesis: the five verified failure classes share three root causes — (1) a *choice point* (which CTA is the job's) is currently answered by a hand-picked CSS selector, (2) a *loop point* (page didn't answer a decision) is answered by retrying, (3) a *state tell* (dead page / auth wall) is read too late, after perception. Fix each with a universal mechanism in code; board data stays as priors, never as the correctness owner. Read-only claims below cite main-repo `file:line`.

## 0. Verified code base (what already exists)

- Board entry click is a single CSS selector made from the graph node: `boards/run.py:349` `entry = page.locator(board["entry"]["selector"]).filter(visible=True).first`, click at `run.py:352`, fallback top-element click `run.py:356-358`, failure → `stop("no_entry")` `run.py:359-364`. `indeed` entry selector = `#indeedApplyButton, button:has-text("Apply now"), a:has-text("Apply now")` (`docs/career-agent/ats-graph.json` node `board:indeed`). "Apply on company site" is not matchable → jobs 30285/30833 die at `no_entry` (30285 recorded as parked-challenge: `data/battle/queue_diagnosis.md:88`).
- Guard layer runs **after** the entry hop: `run.py:388` `_blocked`, `run.py:391-392` `if not on_board(...): return stop("left_board")` (Indeed→company-site handoff exists: `apply.py:456-464`), `run.py:393-394` `is_login_page` → `auth_wall`.
- An *unconditional* generic drill already exists and is unused by the board engine: `page_prep.reach_application_form` (`page_prep.py:628-698`) with affordance scan `find_apply_affordance` (`page_prep.py:546-561`), ad-frame skip `_frame_is_ad` (`page_prep.py:564-571`), loop-safe `exclude` set (`page_prep.py:640-686`), learned routes `_known_clicks` (`page_prep.py:613-625`).
- Label ranking is pure: `_best_apply` (`page_prep.py:440-468`) over `_APPLY_ALLOW`/`_APPLY_DENY` (`page_prep.py:406-418`). Ad frames: `_AD_HOSTS` is a 6-host list (`page_prep.py:421-422`), `_is_ad_frame` needs exactly title `"advertisement"` or `aswift_*` names (`page_prep.py:425-430`). Perception's frame deny list is a fixed host string list (`perception.py:622-628`) and child-frame rows survive if `looks_like_application(rows)` (`perception.py:644-651`, applied in `collect_raw`, `perception.py:684-689`) — a decoy 2-field ad form passes.
- Modal layer: `page_prep.dismiss_dialogs` (`page_prep.py:121-146`) **keeps** any modal containing an apply-name control (`:129-133`, `:I'm ready to apply` is rank-3 in `_APPLY_ALLOW`, `page_prep.py:407`), keeps fillable dialogs (`:135-142`), else clicks `_DIALOG_DISMISS` (`page_prep.py:66`). Called every step by `prepare()` (`page_prep.py:829-834`), wired as `prep_fn` into the LangGraph walk (`apply.py:570-585`, `orchestrator/graph.py:227-245` perceive node).
- Click discipline (one click, wait for what it did): `clicks.act` (`clicks.py:202-261`), `page_signature` (`clicks.py:69-73`), `wait_until_stable` (`clicks.py:139-152`), `wait_for_change` (`clicks.py:269-278`).
- Step caps: board engine `MAX_STEPS = 8` (`run.py:23`); career-site walk `max_steps=args.max_steps` (`apply.py:582`). The 31867 himalayas upsell loop churns these out because every iteration re-encounters the same modal and `dismiss_dialogs` refuses to close a modal that "offers an apply control" while the clicked one does nothing.
- Wall check is DOM-only and *late*: `login_from_signals` (`page_prep.py:252-256`) requires a password box; instahyre's `/candidates/register/` sign-up form has none, so perception happily reports ~26 "job" fields from `snapshot_form` (`perception.py:712-729`). The URL itself (`/candidates/register/`) is never consulted.
- Page-health: `apply.py:398-415` navigates and settles without ever reading `page.url`/body for Chrome error state; `board _blocked` (`run.py:62-74`) checks only challenges. A stale POST replay (`ERR_CACHE_MISS` → `chrome-error://chromewebdata`, job 29987) surfaces as an unreadable page; nothing detects it.
- Credential provider `provide(page, gate, site, original_url, email, phone)` exists and handles guest-apply, stored creds, register-then-login (`browser/credential_provider.py:1058-1134`; guest keywords `:968-972`). It is wired only into the career-site engine (`apply.py:516-527`, `graph.py:147-209`); the board engine's `run_board` ctx never receives it (`apply.py:452-455` passes profile/human but no cred provider).
- Re-run path that triggers D: `queue_runner.run_one_detached` (`queue_runner.py:116-131`) → `apply.py:398` plain `page.goto(args.url)`. Target choice: `queue_runner.job_target` uses `apply_url` only when `apply_kind == "external"` (`queue_runner.py:36-40`) — indeed scrapes leave `apply_kind` empty, so the listing URL is used and the button miss becomes fatal.

## 1. Universal reach-the-form arbitration (class A + C)

**New module `browser/cta_arbiter.py`** (~200 lines), pure, unit-tested. Input: candidate `[{name, role, ref, frame, board_hint}]`. Output: ranked list. Features, in score-decay order:

- `f_label`: phrase prior — reuse `_APPLY_ALLOW` order (`page_prep.py:406-411`) with `_APPLY_DENY` veto (`page_prep.py:412-418`), plus new entries: `"apply on company site"`, `"continue to employer application"`, `"apply on the employer's site"`, `"company site"` (the exact labels class A fails on).
- `f_frame_class`: `main frame > trusted ATS iframe > unknown iframe ≫ ad iframe`. Ad-ness is a generic *score*, not a host allowlist — `_ad_score(frame)`: (a) host contains an ad-network fragment (`doubleclick|googlesyndication|adnxs|casalemedia|criteo|pubmatic|rubiconproject|smartadserver|taboola|outbrain|amazon-adsystem|adservice` — superset of `_AD_HOSTS`, `page_prep.py:421-422`); (b) `title/name == "advertisement"`, `name` starts `aswift_/google_ads_` (keep `page_prep.py:425-430`); (c) DOM markers inside the frame: `[class*=ad- i],[id^=div-gpt-ad],[data-google-av-attrs]` plus ad-slot banner sizes (728x90/300x250/300x600); (d) **framing context**: the host `<iframe>` lives under a container whose class/id matches `ad|advert|banner|sponsor` or the parent page hidden it at load. Score ≥ 2 ⇒ frame is an ad frame; its CTAs get label-prior cap −∞ (never beat a visible main-frame apply), mirroring today's hard skip at `page_prep.py:550-553` but as one ranking feature so an ad frame's *real* apply (rare; e.g. Schweppes-style embed) can still win when everything else is absent.
- `f_position`: computed style `position: fixed|sticky` **and** viewport band. Himalayas' real CTA is a fixed bottom bar (`job 31505`); a fixed bottom-docked control scores a large positive; an element inside an ad frame nearly always sits in a flow container — net negative. Requires one `getComputedStyle`+`getBoundingClientRect` pass per candidate (≤20 elements).
- `f_board_hint`: the board's declarative selector hit and the ATS graph's learned `reach_clicks` (`page_prep.py:613-625`) are a **positive prior**, never a verdict: they lift, but cannot overcome a veto (deny-list name, ad-frame ≥ 2).
- `f_target`: for anchors, `href` destination — an on-site apply path vs an off-site `job/share?tracker` URL — cheap and stable signal (e.g. instahyre relink vs company ATS).

**Arbitration runtime** stays the drill's own proof-of-work: no pre-click foresight needed. Pick top-rank → click once via `clicks.act` (`clicks.py:202-261`) → verify (URL changed / real fields appeared via `is_application_form`, `page_prep.py:481-484`) → if no progress, add ref to the exclude set (drill already does this, `page_prep.py:640-644,681`) → next candidate. Bounded by `max_hops` (`page_prep.py:634`).

**Module boundaries.**
- Replace the entry block `boards/run.py:346-368` with `_pick_entry(page, board)`: candidates = (a) declarative selector hit (one candidate, `f_board_hint` high), (b) `find_apply_affordance` scan (`page_prep.py:546-561`), (c) `_interstitial` hits stay as pre-pass (`run.py:140-148`). Dedup by ref-stamp `data-aff` (`page_prep.py:321-341`). Then click via arbiter order through the same fallback that exists at `run.py:350-358` (top-element click when covered — Instahyre comment `run.py:354-356`).
- Perception-level decoy filter: extend `perception.is_denied_frame` (`perception.py:635-637`) to consult the shared `_ad_score` (one definition, two callers — drill (`page_prep.py:564-571`) and collector (`perception.py:663-690`)), so ad-frame rows never reach the form model even when `looks_like_application` (perception.py:644-651) would admit them.
- Cross-boundary rule: `run.py:391-392` `left_board` and the `apply.py:456-464` handoff remain the *only* bridge to the career-site engine; the arbiter never decides "whose engine" — the URL does.

## 2. Universal modal/dialog layer (class B)

Lives where dialogs already do: `page_prep.dismiss_dialogs` (`page_prep.py:121-146`), plus a new `modal_politics.py`-free archetype chain evaluated *before* the current keep-rules:

1. **Monetization tell wins**: modal text matches `_UPSELL = /generate (a )?(cover letter|resume)|ai (cover letter|writer)|premium|boost|upgrade|credits?|unlock/i` → this modal is a monetization step; dismiss whichever close affordance it offers (close/X/Cancel/"not now"/`aria-label*=close`), *not* its primary CTA. This overrides today's implicit keep-rule (`page_prep.py:129-133`) that lets an upsell survive because it also carries "I'm ready to apply".
2. **Progress CTA tried once, never looped**: if step 1 not matched and the modal offers a progress-style apply name (`_APPLY_ALLOW` order: "i'm ready to apply" before "apply now", `page_prep.py:407-410`), click it **once** through `clicks.act`. Record the modal's signature from `clicks.visible_modal` (`clicks.py:46-54,195-199`).
3. **Identical-snapshot degrade (the 31867 class, mandatory)**: a run-scoped dict `modal_seen: {signature: count}`. When the same modal signature is observed ≥ 2 times with no accepted page change between (`page_signature`, `clicks.py:69-73`), the chain permanently downgrades: step 2 is removed for that signature, step 1's dismiss runs even without an upsell match, and if no close affordance exists, `Escape` + stop-with-reason `modal_loop` instead of burning `MAX_STEPS = 8` (`run.py:23`) or the walk's `max_steps` (`apply.py:582`). Loop budget: degrade after 2 identical snapshots, never 6.
4. **Keep rules unchanged** for fillable dialogs (`page_prep.py:135-142`) and idle-session prompts (`_IDLE_DIALOG_RE`, `page_prep.py:67-68`).

Wiring: `prepare()` (`page_prep.py:829-834`) already runs every perceive step (`graph.py:227-245`); the modal chain consumes state from a small per-run object passed through ctx (board engine: `run.py:299-302`; career-site: `_walk()` ctx `apply.py:579-585`). `trail_note` (`page_prep.py:48-51`) records `modal_aw archetype, degrade=True` for promotion.

## 3. Universal page-health watchdog (class D)

**New `browser/page_health.py`** (~80 lines):

- `chrome_error(page) -> str|None`: URL starts `chrome-error://` **or** body text matches `/ERR_[A-Z_]+/` (`ERR_CACHE_MISS`, `ERR_NAME_NOT_RESOLVED`, …) or Chrome's crash-page UI text; read from the same evaluate style as `_blocked` (`run.py:62-66`), never via fragile `resp` handles.
- `recover(page, intended_url) -> 'recovered'|'dead'`: when the error is a stale-cache (`ERR_CACHE_MISS`) off a re-run (`queue_runner.py:116-131` is exactly the "submit watcher relaunch" path), perform **one** fresh `page.goto(intended_url, wait_until="domcontentloaded")` — navigation from the address bar is a GET, matching the verified live behavior on job 29987 — then `wait_until_stable` (`clicks.py:139-152`). A second error or host mismatch ⇒ `dead`: caller stops with `stopped_reason="dead_page"` (a queue-visible reason like `watchable()` treats today, `queue_runner.py:173-174`).
- Call sites (three, all cheap): (1) `apply.py` right after the first goto (`apply.py:398-415`) with `intended=args.url`; (2) board step loop immediately after `wait_until_stable` (`run.py:386-387`) and inside `_blocked`-adjacent checks, `intended = ctx["intended_url"]` (seeded from `args.url` at `run.py:301`/`apply.py:452`); (3) `perceive_node` before the gate check (`graph.py:227-246`). One recovery per (page, signature) — no retry cascade.

## 4. Login-wall early detector (class E)

Extend `page_prep.is_login_page` (`page_prep.py:259-263`) with a **URL-first** predicate, consulted *before* any form perception:

- `wallish_url(url)`: path segment tokens `(register|signup|sign-up|log-in|login|signin|authenticate|create-account)` in the first two path segments — e.g. instahyre `/candidates/register/` (`job 30076`). Pure function.
- Combined rule `is_wall(page, url)`: `wallish_url(url)` **OR** (`login_from_signals`, `page_prep.py:252-256`) **or** (email-first tell (`credential_provider._is_email_first`, `:221-229`) **and** header-nav auth control ("sign up"/"log in" inside `header,nav,[role=banner]` chrome, mirroring the chrome-skip used at `perception.py:355` and `credential_provider._is_page_chrome`, `:978-986`)). Requiring ≥ 2 corroborating tells keeps job-slug false positives out ("register" inside a JD path) while catching password-less sign-up walls today's checker misses.
- **The wall is never perception**: once `is_wall` is true, skip `driver.fields`/`snapshot_form` entirely (`run.py:396` and `graph.py:302` never run against an auth page), so the "26 job fields" misread (`job 30076`) cannot happen.
- **Delegate, don't imitate**: call the existing `credential_provider.provide` (`credential_provider.py:1058-1134`) — guest-apply first (`:1075-1077`), then register/login (`:1092-1134`). Board engine wiring: `apply.py:452-455` already passes `profile`/`human` into `run_board` ctx; add `"cred_provider": _provide_url` (built at `apply.py:520-521`), and `run.py:393-394` becomes: if `is_wall` → `ctx.get("cred_provider")` → if wall cleared (re-check via `login_from_signals`/URL), continue the loop; else `stop("auth_wall")` as today. This reuses, verbatim, `clear_auth_wall`'s contract (`page_prep.py:389-403`).

## 5. What boards keep vs. code (declared snippets, generic truth)

- Board data (`ats-graph.json` via `profiles.load_boards`, `profiles.py:28-34`) keeps: domains, confirm/challenge/logged-out needles, questionnaire parsers, final/advance label lists (`run.py:81` via `drivers.next_control`, `drivers.py:79-86`), interstitial selectors, daily caps. These are *verification and vocabulary*, cheap to differ.
- Entry selectors become **samples** feeding `f_board_hint`: the arbiter owns correctness. Learned `reach_clicks` (`page_prep.py:613-625`) likewise priors. Nothing in the graph is load-bearing for reaching the form anymore.
- Data entries needed: **none required**. Optional belt-and-braces: set `apply_kind='external'` (1 line each, jobs 30285/30833) so `job_target` (`queue_runner.py:36-40`) routes straight to `apply_url`; the generic path heals the same class without it.

**Healing status per job (generic-only, no data changes):** 30285/30833 healed by A (label + arbiter + left_board handoff `apply.py:456-464`) · 31867 by B (archetype chain + 2-snapshot degrade) · 31505 by A/C (ad-frame score demotes decoys; real sticky bar wins `f_frame_class`+`f_position`) · 29987 by D (one fresh GET) · 30076 by E (URL tell + cred provider)。

## 6. Failure modes, what generic cannot fix, regression risk

| Risk | Mitigation |
|---|---|
| Arbiter picks a decoy **inside the main frame** (promo tiles, "Easy Apply" widget for a *different* job) | label priors + exclude-on-no-progress (`page_prep.py:640-644`); `f_target` off-site check |
| Upsell regex closes a **mandatory** step (site requires cover letter upload framed as upsell) | dismiss only when a close/X affordance exists AND a fillable-dialog keep-rule (`page_prep.py:135-142`) didn't retain it; `modal_loop` stop is observable |
| Wall-URL regex false-positives (job slug contains "register") | first-two-segments scope + ≥2 tells |
| Ad-score overreach marks a genuine ATS iframe ad-y | ad dismissal needs score ≥ 2 *and* `f_board_hint` still available; drill exclude-set self-heals one misrank |
| Extra frame scans per click (perf) | single `_CLICKABLES_JS` pass reused from `page_prep.py:321-341`; ≤20 computed-style reads |
| **Where the declarative school wins (honest)** | sites with rock-stable syntax (Naukri `button.apply-button`, LinkedIn `Easy Apply`) are matched *harder and cheaper* by one JSON line; generic code pays scan+rank cost every run and can still misrank novel shells (e.g. full-screen interceptors drawn over everything where position priors invert). Those one-off shells are exactly what the learned reach_path data encodes. |

## 7. Task breakdown (≤0.5d each)

1. `cta_arbiter.py` ranker + `_ad_score` (pure, unit tests) — 0.5d
2. `_APPLY_ALLOW` additions + replace `run.py:346-368` entry block with arbiter pick — 0.5d
3. Ad-frame scoring shared into `perception.is_denied_frame` + row filter + tests — 0.5d
4. Modal archetype chain + `modal_seen` degrade + tests (`page_prep.py:121-146`, `829-834`) — 0.5d
5. `page_health.py` + wiring (`apply.py:398-415`, `run.py:386-388`, `graph.py:227-246`) — 0.5d
6. `wallish_url` + `is_wall` + cred-provider into board ctx (`apply.py:452-455`, `run.py:393-394`) — 0.5d
7. Live replays: 30285, 30833, 31867, 31505, 29987, 30076 — 0.5d

Total ~3.5d.

## Claims table

| failure class | generic mechanism | file | lines changed (est.) | risk |
|---|---|---|---|---|
| A 30285/30833 | CTA arbitration + employer-site labels; `left_board` handoff already exists | `browser/cta_arbiter.py` (new), `boards/run.py:346-368`, `page_prep.py:406-418` | ~150 | med — main-frame decoys |
| B 31867 | modal archetype chain; degrade to dismiss after 2 identical modal snapshots | `page_prep.py:121-146, 829-834` | ~70 | low-med — mandatory-modal mis-dismiss |
| C 31505 | ad-frame score (host/DOM/position) ranks decoys below fixed main-frame bar; perception denies ad rows | `cta_arbiter.py`, `page_prep.py:421-430,546-571`, `perception.py:635-637,684-689` | ~80 | low |
| D 29987 | page-health watchdog: detect `chrome-error://`/`ERR_*`, one fresh GET, re-perceive | `browser/page_health.py` (new), `apply.py:398-415`, `run.py:386-388`, `graph.py:227-246` | ~90 | low — GET may hit challenge → existing challenge path |
| E 30076 | URL+header-nav wall detector before perception; delegate to `credential_provider.provide` | `page_prep.py:252-263,393-403`, `boards/run.py:393-396`, `apply.py:452-455` | ~60 | low — slug false-positive guarded |
| A-routing (opt.) | `apply_kind='external'` data entry, 2 jobs | `data/jobs.db` via queue | 0 code | none |
