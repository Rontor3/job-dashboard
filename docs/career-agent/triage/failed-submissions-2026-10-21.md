# Failed-Submission Triage — Oct 17–21, 2026

Scope: `apply_queue` rows `state='parked'` with `started_at >= 2026-10-17` (32–38 rows), plus failed-by-domain runs outside the queue (himalayas/31505, wadhwani/31867, Twilio greenhouse/30889, Indeed daily-cap 31870/31686). Evidence: per-run stdout `data/agent_runs/<id>.log` (read line by line), `run_log` rows incl. `result_json`, artifact folders `data/agent_runs/<id>/` (screenshots opened for A, B, C, E, I-jobs), `submit_history` (no parked job appears as a confirmed submission, so no double-submission contamination).

Sources queried read-only: `data/jobs.db` tables `apply_queue`, `run_log`, `submit_history`, `submission_watch`. No files modified except this doc.

---

## 1) Summary table

| # | Class | Jobs affected (window) | Frequency | Severity | One-line root cause |
|---|-------|------------------------|-----------|----------|---------------------|
| A | **no_entry / external-apply detection** | 30285, 30833, 30071 (+ close cousin 28033) | 3 in window; `no_entry` 6× in run_log vs 31 pre-window — pre-existing, rate ~same | High | Entry locator `#indeedApplyButton, button:has-text("Apply now"), a:has-text("Apply now")` blind to Indeed's "Apply on company site" CTA → 5s `TimeoutError: Locator.evaluate` → `no_entry` |
| B | **Modal/dialog arbitration** (himalayas upsell) | 31867 | 1 job, 4 failed runs Oct 20 | High | "Don't let your application get lost in the pile" AI-upsell modal stays open; agent loops `no_form_found`→`no_advance_control` instead of clicking "I'm ready to apply" |
| C | **Ad/decoy 'Apply Now' vs real sticky CTA** (himalayas ad-iframe) | 31505 | 1 job, 12 failed runs Oct 19–20 (`no_form_found` ×11, `site_refused` ×1) | High | In-page ad unit carries an identically-labeled "Apply Now" next to the real full-width sticky "Apply now"; arbitration never resolves, nothing opens the form |
| D | **Nav to chrome-error page** after failed credential step | 29987 (Deloitte USI) | 1 job (first seen Oct 20 — `chrome-error` grep hits only this log) | Medium | Cred provider can't clear Deloitte login wall; post-cred navigation lands on `chrome-error://chromewebdata/` (ERR_CACHE_MISS family) and perception keeps re-surveying 0 fields |
| E | **Login/session state not pre-checked / auth-wall handling** | 30076 (instahyre), 30233 (Accenture B2C), 29998→30998 (MetLife register) | 3 jobs; `auth_wall` 11× recent vs 17 pre, `logged_out` 1× recent vs 4 pre — pre-existing | Medium | Application run dispatched with logged-out session → bounced to signup/register wall; creds provider gives up mid-signup ("the account does not exist") |
| F | **Node helper EPIPE crash mid-ask** | 30604, 29815 (window) + 29594, 29805, 30034, 30017, 29994, 30580, 30212 (older) | 9 logs total; 2 in window — pre-existing since Oct 4 | High | Local answer/ask channel dies with `Error: write EPIPE` (Node v24.18.1) during `[board] asking:`; the job never completes and gets parked under a misleading reason (`needs_answers` / `stalled_no_progress`) |
| G | **Custom-select "did not take" escalation loop** (Workday-family Hangul band fields) | 30901 (MKS), 30026 (Salesforce), 29764 (Redica), 30998 (MetLife), 30889 (Twilio), 30285-avature leg | 6 jobs in window — biggest run-killer of the window | High | Workday-style selects (`How Did You Hear About Us?*`, `Country Phone Code*`, `Language Variant`, band multi-selects) reject the answer → `pending_human` → telegram wait → no progress → stall |
| H | **Daily cap / policy stops** (not bugs) | 30925, 31870, 31686, 29715, 29725, 29742, 29747, 29749, 30090, 30092, 30457, 30528, 30178, 29839, 29669, 31321, 30886, 29988 | largest count in window; pre-existing (`daily_cap` 10×, `apply_is_one_click` 3×, `gate:recaptcha_v2_checkbox` 21× pre-window) | Info | Intentional gates: 24h submit cap (5/5), "first submit on site must go through you", judgment-source review, dry-run probes, closed postings |
| I | **Misc one-offs** (see tickets) | 29991 (Hitachi autofill cycle), 28033 (naukri chat drift), 30255 (careers landing shell), challenge family 30209/30609/30378/30317/29278 | 8 jobs | Medium | Individually distinct: Workday wizard step-cycle loop, `._chatBotContainer` selector drift, 124-field careers page, Cloudflare "Additional Verification Required" walls |
| J | **OTP autofill failure loop** (Accenture B2C) | 30221 | 1 job (grep: no other `OTP fill result: False` logs) | Medium | Inline-verify OTP retrieved but `OTP fill result: False` every time; retried 16+ times with the same stale code |
| K | **Human/telegram answer ingestion corrupt** | 29669, 31321 | 2 jobs | High (hidden data-quality risk) | Human-sourced answers carry conversational filler into wrong fields: `School* = 'Not provided in text'`, `How did you hear about us? = 'Since you did not provide the source of your application'` |

Pre-existing vs recent: classes **A, E, F, H, and the challenge family** all exist pre-Oct-17 (`GROUP BY stopped_reason` on `run_log` ts<2026-10-17: `no_entry` 31, `auth_wall` 17, `daily_cap` 10, `logged_out` 4, `apply_is_one_click` 3, `sensitive_field` 1, `gate:recaptcha_v2_checkbox` 21). New run_log reasons that appear first in this window: `no_form_found` (20 — classes B/C), `stalled_no_progress` (0 run_log rows ever — stalls never wrote run_log), `site_refused` (1). New specific behaviors: D (chrome-error), J (OTP loop), K (junk human answers), G in bulk, F continuing.

---

## 2) Per-job tickets

### Class A — no_entry / external-apply detection

**Job 30285 — Koch (koch.avature.net) via Indeed `viewjob?jk=09e5c56e34c7684b`** — parked (latest: `no_entry` 2026-10-20 21:46)
- stopped_reason (run_log row 841): `no_entry`, error in result_json: `TimeoutError: Locator.evaluate: Timeout 5000ms exceeded. Call log: waiting for locator("#indeedApplyButton, button:has-text(\"Apply now\"), a:has-text(\"Apply now\")").filter(visible=True).first`
- Evidence `data/agent_runs/30285.log:13`: `[assist 1/5] asking Claude — no_entry on in.indeed.com/viewjob`; `:14`: `Claude replied: "You've hit your weekly limit · resets Oct 22 at 5:30am (Asia/Calcutta)"`; `:15`: `Claude chose: invalid —`
- Screenshot `data/agent_runs/30285/perceive0.png`: the only CTA on the Indeed viewjob page is the blue **"Apply on company site"** button (Koch DS job). No `#indeedApplyButton`/"Apply now" exists on this page — the locator cannot match, so it times out.
- Assignment: **A**.
- Later runs on the avature direct URL (rows 750–754, 764, 772, 781, 785) escalated `'Current? '` ×2 then ended `stuck`/`no_advance_control` with 17–51 filled — a G-family sideline.
- What a fix must guarantee: entry selector must include the external-apply variant ("Apply on company site") with its `href`/target extraction guaranteeing navigation to the company ATS URL within timeout bounds, plus a pre-click check that a jump to the ATS domain occurred.
- Mitigating context: assist escalation was unavailable Oct 20 evening regardless (Claude weekly rate limit), so the park was the correct conservative outcome.

**Job 30833 — Indeed `viewjob?jk=5f32b6cc405d4078` (QualityKiosk "Data Annotator AI")** — parked `no_advance_control` 22:08 Oct 20
- run_log row 834 `no_entry`, error identical to 30285 (same locator timeout). `data/agent_runs/30833.log:12-16`.
- `data/agent_runs/30833/perceive0.png`: same "Apply on company site" CTA (QualityKiosk), ad banner above; no internal Apply now.
- Assignment: **A**. (Row 840 `no_advance_control` is the retry appended; no log was written for the 22:06 retry — stdout capture lost, see loose ends.)

**Job 30071 — instahyre `job-443444-data-scientist-at-geoiq-bangalore`** — parked `no_entry` Oct 18
- `data/agent_runs/30071.log:10`: `[assist 1/5] asking Claude — no_entry on www.instahyre.com/job-443444-...`; `:13` result_json error: `TimeoutError: Locator.evaluate: Timeout 5000ms exceeded ... waiting for locator("button:has-text(\"Apply now\")")`.
- `:11` (assist replay): `Claude chose: give_up — Already applied: the page shows an 'Application sent!' button dated October 3, 2026...` — i.e., the entry was genuinely absent (already-applied state), not just selector drift.
- Assignment: **A (instahyre variant)** with an already-applied sub-cause that should be detected before the timeout, not via Claude after it.

### Class B — Modal arbitration (himalayas upsell)

**Job 31867 — himalayas wadhwani-ai `machine-learning-scientist-asr`** — no queue row; failed runs Oct 20 (rows 809/812/820/827: `gate:cloudflare_interstitial`, `no_form_found`, `no_form_found`, `no_advance_control`)
- **No `.log` file exists** for this job (see loose ends) — evidence is run_log + screenshots: `data/agent_runs/31867/perceive1_2..6.png` = 5 consecutive modal snapshots (the "6 retries" pattern), all showing the upsell dialog **"Don't let your application get lost in the pile"** with `Generate cover letter with AI` / `Generate resume with AI` / **`I'm ready to apply`** and `Don't show this again`, over the blurred application form.
- Assignment: **B**.
- What a fix must guarantee: any visible centered dialog with primary CTA "I'm ready to apply" (or "Skip") over the perceived form must be resolved (click the continue-CTA, or persist the "Don't show this again" acknowledgement) before the no_form_found/no_advance_control determination is made, and resolution of the same modal state must not fail more than once without escalating.

### Class C — Ad/decoy 'Apply Now' inside ad-iframe vs real sticky CTA (himalayas)

**Job 31505 — himalayas/upstart `staff-applied-scientist`** — not in apply_queue; registered in `submission_watch` (`how='site_refused'`, created 2026-10-20 21:43, run_key=run822)
- run_log rows 791/792/794/795/796/803/804/805/806/819/820 (Oct 19 20:50 → Oct 20 10:06): `no_form_found` ×11, zero-filed every time. Row 822 Oct 20 12:02: `site_refused`.
- **No `.log` file** — screenshot evidence: `data/agent_runs/31505/perceive0.png` (page top): an ad unit "Fast-track to EiR roles — Mesa School of Business" with its own **"Apply Now >"** next to the AdChoices info markers, AND the real **sticky full-width purple "Apply now"** at page bottom. `perceive0_6.png` (page bottom): a second dark-green ad box "Build 4 Startups in 12 Months" with its own **"Apply Now"** (AdChoices `ⓘ ⋮` icons visible at its top-right) directly above the same sticky purple "Apply now".
- Assignment: **C**. Two near-identical decoy CTAs from ad units (perceive frames 0–6 = six frames scanned per attempt, three attempt-batches preserved: perceive0*, perceive1*, perceive2*, perceive3*) defeat the form-opener arbitration; the run concludes `no_form_found` every revisit.
- What a fix must guarantee: in cross-frame/CTA arbitration, identical "Apply Now(s)" in ad-registered iframes (AdChoices-marked) must be excluded from click candidates; the page-sticky primary CTA (full-width, position:fixed bottom) must win; repeated `no_form_found` on the same URL should decay to park-with-telegram, not be re-run 11 times across 15 hours.
- Side effect: repeated re-opens of the same tab may have contributed to row 822 `site_refused` registering.

### Class D — Navigation to chrome-error page

**Job 29987 — usijobs.deloitte.com USI Product Engineer** — parked `no_advance_control` Oct 20 15:23 (also `auth_wall` ×2 Oct 18, `sensitive_field` Oct 18, `no_advance_control` Oct 18 17:33)
- `data/agent_runs/29987.log:6-7`: `[reach] enter url=usijobs.deloitte.com/... JobDetail` → `exit status=password`; `:9-39`: cred provider burns snapshot loops (`no change after 30s (navigate_form/wall_submit/pw_submit)`), retires stored login (`[cred] usijobs.deloitte.com: the stored login did not open — retiring it and registering`), guest apply scan dies (`Error('Page.query_selector_all: Execution context was destroyed, most likely because of a navigation')`), `no signup form found — escalating`, outcome `unhandled:register`.
- `:41`: `[reach] enter url=chrome-error://chromewebdata/` — the post-credential navigation lands on a **chrome-error page** (ERR_CACHE_MISS family). `:43`: `[password] after the credential step: kind=none url=chrome-error://chromewebdata/`; `:48/51/55`: all three perception frames are `chrome-error://chromewebdata/`, `snapshot: 0 fields`; `:57-59`: assist asked Claude — blocked by **weekly rate limit** ("You've hit your weekly limit · resets Oct 22 at 5:30am"); run parks `no_advance_control` with `steps:1, form:[]`.
- Assignment: **D**.
- Related same-ticket sub-behavior: Oct 18 18:31 run (row 743) parked `sensitive_field` with escalated_labels `["Gender *"]` — a Deloitte demographic question the filer refuses to answer autonomously (correct policy, pre-existing `sensitive_field` class, one instance pre-window: job 29530 Oct 4).
- What a fix must guarantee: after a failed credential step, the runner must re-load the original application URL (not post-cred result) and detect `chrome-error://` / `ERR_*` navigation states immediately — treating an error-chrome page as a retryable navigation failure rather than a "site with 0 fields" perception target; assist fallback failing (rate limit) must not prevent a clean retry classification.

### Class E — Login/session state not pre-checked / auth-wall handling

**Job 30076 — instahyre `job-443227-senior-data-scientist-at-razorpay-gurgaon`** — parked `logged_out` Oct 20 19:32
- `data/agent_runs/30076.log:8-9`: frame 0 is the job page, `perc snapshot: 26 fields` (signup form + marketing widgets); `:11` result_json: final `url = https://www.instahyre.com/candidates/register/` — bounced to the **signup wall**; policy ran `auto-submit ALLOWED` before the login-state check, so the wall was only classified after 26 fake form fields were storyboarded.
- `data/agent_runs/30076/perceive0.png`: full **Sign up** page (`Sign up with LinkedIn` / `Sign up with Google` / `Get started →`).
- Assignment: **E**. 26 fields counted on the signup page is the signature of what the task called "signup wall counted 26 fields".
- What a fix must guarantee: per-site login pre-check before form work (e.g., auth-wall bounce detection on redirect to `/candidates/register/`), and perception must not treat register/login forms as application forms.

**Job 30233 — accenture.com jobdetails (B2C wall)** — parked `auth_wall` Oct 18 16:39
- `data/agent_runs/30233.log:16-27`: nav click → `state: password` repeatedly; `:21`: `the stored login did not open — retiring it and registering`; signup reached `inline_verify`, OTP got `855051`, then `:31`: `no password box yet — nothing saved, the account does not exist`; `:33`: `[stop] credential provider could not clear the login wall. Log in manually in the open browser, then re-run.`
- Assignment: **E** (Accenture/B2C variant; pairs with incident 30221 in Class J below).

**Job 29998→30998 — MetLife `metlifecareers.com .../Senior-Data-Scientist-I-Chaitanya/20925`** — parked `auth_wall` Oct 18 (queue reason), then repeated MetLife runs Oct 19 (rows 746–749, 753, 773) ended with empty stopped_reason, `__interrupt__` on `Degree *` + `Language Variant`
- result_json of the last runs: `pending_human` retains `'Degree *'` (education select; the post-submitted-row duplicate select was passed) and `'Language Variant'` with **`'options': []`** — a dependent select whose options only populate after `Language` is chosen, which the perception never re-reads; the run keeps filling 37–42 decisions and interrupt-looping.
- Assignment: the parked `auth_wall` label is stale/masked; the true recent behavior is the **G-family dependent-select interrupt** — ticketed fully in Class G below (30998).
- What a fix must guarantee: re-snapshot dependent select options after the controlling select is set before declaring a field un-answerable; retry count on the same interrupt ids must be bounded.

### Class F — Node helper EPIPE crash mid-ask

**Job 30604 — Indeed `viewjob?jk=4e1dda44f75c6700` (smartapply review-m form)** — parked `needs_answers` Oct 20 15:35
- `data/agent_runs/30604.log:21-22`: `[answer] 1 fields worked out` → `[board] asking: ['Get email updates for the latest senior data scien']` — then `:23-36`: `node:events:487 ... throw er; // Unhandled 'error' event ... Error: write EPIPE ... Node.js v24.18.1`. The ask channel died mid-question; nothing further ran.
- Artifact folder `data/agent_runs/30604/`: only `tab.json` (46 bytes, `{"tab_id": "773843CC2EBA03AAE8C5269372E5D939"}`) — **no screenshots saved**, matching the task note. No run_log row exists for job 30604 at all (the crashed run never reached `[run_log] recorded`).
- Assignment: **F**. Parked reason `needs_answers` conceals a crash; the job is not actually "awaiting Telegram answers" — it is dead-unanswered.

**Job 29815 — naukri (chat board) `job-listings-agentic-ai-data-scientist...`** — parked `stalled_no_progress` Oct 20 19:32
- `data/agent_runs/29815.log:39`: `[board] chat asked something not in our answers: 'managed model monitoring validation and performance tracking...'`; `:40`: `[board] asking: ['What is your experience deploying and monitoring M', 'Please select the city you are currently residing ']`; `:41-56`: identical EPIPE stack, run dead mid-ask. Parked as `stalled_no_progress`, i.e. another **F masked as a stall**.
- What a fix must guarantee: (1) the Node ask-helper must survive/cancel-abort a failed pipe write (EPIPE on stdout cannot kill the answer flow); (2) a crashed run must record run_log with a distinguishing reason (e.g. `helper_crash`) so the queue doesn't consume extra cycles re-classifying it; (3) EPIPE-classified jobs must not be re-queued under `needs_answers` without actually sending the questions.
- Frequency note: 9 EPIPE-containing logs (`grep -l EPIPE data/agent_runs/*.log`): 29594 (Oct 4), 29805 (Oct 7), 30034 (Oct 7), 30017 (Oct 8), 29994 (Oct 9), 30580 (Oct 15), 30212 (Oct 16), 30604 (Oct 20), 29815 (Oct 21) — pre-existing infra weakness, recurring over 17 days, not a regression.

### Class G — Custom-select "did not take" escalation → telegram stall

**Job 30901 — mksinst (MKS) Workday `Data-Scientist_R23304`** — parked `stalled_no_progress` Oct 20 19:47 (window's longest stall, 13:51)
- `data/agent_runs/30901.log:80-81`: `[fill] did not take: 'How Did You Hear About Us?*' = 'Job Board'` and `[fill] did not take: 'Country Phone Code*' = '+91'`; `:85`: `[fill] step 2: 10 filled, 2 escalated`; `:87`: `[telegram] sending 1 field question(s) — waiting for reply...` (log ends watching).
- Both fields are trivially bankable (India phone code +91; HDYHAU=Job Board) — assignment: **G**, with the task's "bank-answerable escalation" flavor.
- Note: no run_log row was written for the Oct 20 stall (only Oct 19 row 761 `reached_submit_dry_run` exists) — stalls don't write run_log.

**Job 30026 — salesforce.wd12 Workday External_Car** — parked `stalled_no_progress` Oct 17 11:27
- `data/agent_runs/30026.log` tail: the exact same pair: `[fill] did not take: 'How Did You Hear About Us?*' = 'Job Board'` / `'Country Phone Code*' = '+91'` → `step 2: 12 filled, 2 escalated` → `[telegram] sending 1 field question(s) — waiting for reply...`. Near-duplicate pin of **G** on a second Workday tenant.

**Job 29764 — Redica via SmartRecruiters oneclick-ui (jobs.smartrecruiters.com)** — run Oct 19 (not in apply_queue)
- `data/agent_runs/29764.log`: `[fill] did not take: 'City' = 'Mumbai, India'` (City combobox has `'options': []`), `#noPolicy` GDPR checkbox already `'value': 'on'` yet stays in `pending_human`; `:→ [park] ⏸ 1 question(s) parked for this job: Please be informed that your application to this job offer w —` `(label truncated)` `answer them on the tracker, then re-queue`; `[telegram] received 0 answer(s)`.

**Job 30998 — MetLife register (see Class E above)** — `__interrupt__` with `'Degree *'` and `'Language Variant'` `'options': []`, 4+ runs escalating the same two fields (rows 746–749, 753, 773, escalated 2–4). G-variant: dependent dropdown options never re-snapshot.

**Job 30889 — Twilio greenhouse `job-boards.greenhouse.io/twilio/jobs/8258587`** — loop Oct 13→19, not in apply_queue — rows 682–689 and 765/774/782/786: repeated runs with `escalated=9`/`11` on the band multi-select (`Careers Website, LinkedIn, Twitter, Glassdoor, Indeed, Twilio Blog, Conference or Event, Content (e.g. videos, ads, billboards etc), Other` + 2× `Acknowledge`), stopped_reason empty — the run never concludes because the band is escalated wholesale.
- What a fix must guarantee (G united): a select whose set value was rejected must (a) retry with the value re-typed after arm dismiss (Workday custSelect quirk), (b) fall back to a bank answer from the user's country/profile (+91, Job Board), and (c) for band questions, answer the well-known multi-select block deterministically instead of escalating each label; telegrams must only carry real blockers; and an interrupt on the same field triple must be capped.

### Class H — Daily cap / policy stops (working as intended — separate from bugs)

- **30925 (naukri chat, quess)** — `data/agent_runs/30925.log:10`: `[policy] auto-submit not allowed: daily cap reached (5/5 automatic submits in 24h)`, `switch autosubmit_naukri used 5 cap 5`. Queue reason recorded as `one_click_needs_autosubmit`, but the log's true blocker is the daily cap — reason naming is conflated (ticket-note, not a failure).
- **31870 / 31686 (Indeed, naukri)** — run_log rows 802/808/811: `daily_cap` ×3 Oct 20.
- **One-click first-submit gates (instahyre 29715/29725/30457, iimjobs 29742/30092/29747/29749/30090)** — `data/agent_runs/29715.log:9`: `auto-submit not allowed: first submit on instahyre.com must go through you` (parked `one_click_needs_autosubmit`); 29742/30092: same gate for iimjobs (perc frame 1 = `logs.iimjobs.com/tds` pixel, 169-170 fields = tracker noise).
- **29839 (wellfound, `jobs/4780401-data-scientist`)** — `data/agent_runs/29839.log:22`: `auto-submit not allowed: 1 answer(s) not yet autonomous: What interests you about working for this company? (judgment: not a confirmed answer)` → `ready_for_review`, eligibility block says `judgment: not a confirmed answer`, switch `autosubmit_wellfound used 4 cap 5`. Assignment: **legit policy** — the cover-letter free-text was generated by judgment and per-class policy must see human review before an auto submit; not a bug. The answer staged in `decisions` is on-topic and non-harmful (skills/EDA focus), but the gate is doing its job.
- **`reached_submit_dry_run` family** (29669 Kroll/Oracle, 31321 Indeed→Navan-embedded widget, 30886 insyncanalytics, 29988 Scalio Google Form): per-run fills completed (21/24/10/8 fields in dry-run), then stopped by (a) `auto-submit is off for career_site`, (b) unconfirmed `qbank_likely`/`judgment` answers, (c) `first submit on <domain> must go through you`. Intentional gates; see Class K for the junk-value issue inside 29669/31321.
- **Closed postings 30528/30178**: `data/agent_runs/30528.log` / `30178.log`: `[skip] this posting is closed or no longer available.` — informational park, no fix needed beyond marrying queue reasons (`closed`).

### Class I — misc one-offs

**I1. Job 29991 — hitachi.wd1 Workday (Bengaluru AI-ML Engineer; R01033957)** — parked `stalled_no_progress` Oct 18 18:58
- `data/agent_runs/29991.log:64-100`: assist toggles between `click 'Continue'` and `click 'Select file'` on the **`autofillWithResume`** Workday wizard step; field count cycles 30→13→11→9→30 without advancing (`[click] 'Continue': .../apply/autofillWithResume -> .../apply/autofillWithResume` — same URL). Log **ends abruptly mid-run at `[fill] screen 4: 15 decisions, 0 escalated`** with no terminal frame (crash-trace absent — see loose ends).
- Prior run_log for 29991: row 734 `no_advance_control` (1 filled) and 741 `advance_failed` Oct 18 — same page family.
- Assignment: **I1** (Workday autofill-with-resume step-cycle loop).
- What a fix must guarantee: an assist cycle that repeats the same URL/step transition N (>2) times must hard-stop with a distinguishing reason instead of relying on the watcher stall; a resume-uploaded step must be marked complete so Continue-order doesn't flip-flop.

**I2. Job 28033 — naukri chat (Volkswagen Group Technology Solutions)** — parked `unconfirmed` Oct 18 08:01
- `data/agent_runs/28033.log:10`: `[board] chat container '._chatBotContainer' not found; chat-like elements: ['chatbot-container :: ']` — naukri's chat selector has drifted; `:12` assist Claude: `give_up — The page shows a green 'Applied' badge ...` (already applied on Naukri). Run parks `unconfirmed`.
- Assignment: **I2** (board-DOM drift + already-applied state). Same `board:naukri (chat)` board as the 29815 crash.

**I3. Job 30255 — infoveritech.com/careers/ (careers landing shell)** — parked `stalled_no_progress` Oct 18 08:57
- `data/agent_runs/30255.log` tail: `perc snapshot: 124 fields` on the careers **index** page (not a job form); `step 1: 4 filled, 1 escalated`; `[telegram] sending 1 field question(s) — waiting for reply...` — generic contact-me form treated as the application form. Earlier rows 729 `reached_submit_dry_run` (5 filled).

**Challenge / anti-bot family — 30209, 30609, 30378, 30317, 29278 (all `in.indeed.com/viewjob`)** — parked `challenge` / `no_advance_control`
- All five logs are uniformly ~5 lines to the conclusion — e.g. `data/agent_runs/30209.log:6-8`: `[board] board:indeed (form) probe=False` → `[run_log] recorded` → `{... 'stopped_reason': 'challenge' ...}` with `decisions: []`; the board stops pre-perception. `data/agent_runs/30209/perceive0.png`: Indeed interstitial page **"Additional Verification Required — Your Ray ID ... a4da5fd28d0247f6"** with the Cloudflare **"Verify you are human"** Turnstile box (site key marker `Ray ID`), a fresh "Return home" button.
- 30609 shows the escalation order (`auth_wall` rows 719/724/726 Oct 18 → `challenge` Oct 19/20 15:20); 30378 (jk=47f339a3c61e552c) shows the reverse (`reached_submit_dry_run` Oct 18 morning → `challenge` 11:07). Same page cycles challenge/auth flows across hours — consistent with Indeed-side bot throttling, verified per fresh page load.
- Assignment: challenge/anti-bot (pre-existing class: 8 challenge + 21 `gate:recaptcha_v2_checkbox` + 1 `gate:cloudflare_interstitial` pre-window). Precise stop point: pre-perception on job page load; `pending_human: []` — nothing was answered.
- 30209 note: queue shows it started again at 22:04 Oct 20 and parked `no_advance_control` at 22:05 (row 832 `challenge` 19:19 → queue-dump out-of-date in the task's first query) — i.e., the challenge bounce and the next no_advance_control are paired half-sessions.

### Class J — OTP autofill failure loop (Accenture B2C inline_verify)

**Job 30221 — accenture.com jobdetails via b2cprejoinerprod.b2clogin.com (ATCI-5218036 LLM Operations Engineer)** — parked `stalled_no_progress` Oct 18 17:20 (queue), run_log row only Oct 6 `no_advance_control`
- `data/agent_runs/30221.log`: `[cred] sent the inline verification code` → `[gmail-otp] Got code '801419' from no-reply@careers.accenture.com` → `[cred] got OTP code='801419', filling now` → `[cred] OTP fill result: False` → `[cred] OTP submit clicked: True` → `post-OTP state: verify_email` → **repeated exact block 16+ times with the same code** (16 identical `OTP fill result: False` lines), the credential loop never notices that the same OTP can't work (single-use) and re-polls Gmail (which keeps serving the same email → infinite).
- Assignment: **J**. grep `OTP fill result: False` across all `data/agent_runs/*.log`: only 30221.has it — recent one-off, different from 30233's E-variant (that one saved the credential then failed at the password step).

### Class K — Human/telegram answer ingestion corrupt

**Job 31321 — Indeed `viewjob?jk=6f68f3c3675055e1` → Navan-branded embedded application (`/careers/openings/8287469`)** — parked `reached_submit_dry_run` Oct 18 08:39
- `data/agent_runs/31321.log` (result_json): decision `{'ref': 'f1@@#school--0', 'label': 'School*', 'value': 'Not provided in text', 'action': 'combobox', 'source': 'human'}` — a School combobox fed the literal conversational filler **from the human-repplied escalation context**, not an actual school; remaining schooling left "Not provided in text" would have submitted garbage had the auto-submit gate been on. Dry-run gate caught it (assignment: **K**, near-miss).

**Job 29669 — careers.kroll.com Oracle (Data Scientist I, Manila)** — parked `reached_submit_dry_run` Oct 17
- result_json (row 709 final): decision `#30000107193329-7 'How did you hear about us?' value 'Since you did not provide the source of your application' source 'human'` — same corruption pattern on the referral-source combobox; the fill failed earlier with `did not take: 'How did you hear about us?' = 'Job Board'` (grep hit in 29669.log) and the "human" reply text was injected verbatim as the value.
- Assignment: **K**. What a fix must guarantee: human/telegram replies must pass a value-validation/constraint step before being committed to `decisions` as form values; filler cell ("Not provided in text", whole sentences) must be rejected and re-escalated instead of wandering into comboboxes.

---

## 3) Loose ends (could not fully classify)

- **Missing stdout logs**: `data/agent_runs/31505.log` and `data/agent_runs/31867.log` **do not exist** — the two himalayas classes (C/B) are evidenced only by run_log rows + screenshot folders. Every other ticket has a log. This means park/finish milestones for himalayas runs lose the full narrative ([board]/[assist]/[fill] story).
- **30833 log not appended**: the Oct 20 22:06 retry on 30833 (row 840 `no_advance_control`) never appeared in `data/agent_runs/30833.log` — log mtime predates the retry; the retry's stdout went nowhere retrievable.
- **Stalls write no run_log**: the four stalled parked jobs in the window (29815, 29991, 30026, 30221, 30901, 30255) have no `stalled_no_progress` run_log rows at all — `run_log` has never contained that reason; the queue reason comes from the watcher. Any audit of "what stalled" must rely on the stdout logs alone.
- **29991 log truncated mid-flow**: `data/agent_runs/29991.log` ends at `[fill] screen 4: 15 decisions, 0 escalated` with no terminal frame or crash signature — cause of the abrupt end (kill vs truncation) unknown.
- **30604 screenshots**: folder contains only `tab.json` (46 B) — no perceive/assist PNGs, consistent with the task note but unexplainable from artifacts (crash happened after perception; PNGs were not persisted).
- **31505 `site_refused` (row 822)**: result_json is only 24 chars unless documented elsewhere; cause of the explicit "site refused" verdict on that particular revisit not recorded in any artifact I inspected.
- **Assist channel outage**: at least 3 window jobs (30285, 30833, 29987) show the Claude escalation rejected with "You've hit your weekly limit · resets Oct 22 5:30am" — cannot distinguish whether successful assists would have flipped these tickets; the log lines exist but outcomes can't be replayed retroactively.
- **30998 MetLife run_log rows with empty stopped_reason** (746–749, 753, 773) classified only via result_json (`__interrupt__` payloads); whether the empty reason is a run-kill or a watch-timeout label is not recorded.
- **Jobs 30090/29747/29749** (one-click family) only have run_log rows consumed via `apply_is_one_click`; small logs exist for 29747/29749 family pattern only (identical first-submit gate), no full per-ticket detail was pulled beyond spot checks.
