# Career Agent — Orchestrator, Recall & Feedback Design

**Date:** 2026-08-31
**Status:** Design locked; partially built (perception/fill/collector done — see §11).
**Scope:** The agent that fills and submits ONE job application flawlessly, its answer/recall system, the feedback loop, and the human review surface. Queue/scheduling/dedup are the **dashboard's** job, out of scope here.

---

## 1. Scope boundary — agent vs dashboard

- **Agent (this spec):** given a job + its URL, fill and submit *that one application* correctly — perceive the form, interpret each field, fill the right values, compose/customize answers, handle the human gate, submit.
- **Dashboard (separate):** search for new jobs, the queue, per-application state across runs, dedup, preserving submitted URLs, and the **hourly schedule** that triggers the agent per job. The dashboard invokes the agent (`career_agent.apply` CLI: `--url`, `--job-id`, `--submit`; or `step_engine.walk(...)`).

## 2. Orchestration — Claude is the interpretation brain, not the driver

Two things kept separate:
- **Mechanical execution** (read DOM, click, type, upload, screenshot) — deterministic tools; reliable; a click is a click.
- **Interpretation** (what is this field, is it required, which option, which button advances, is it even a question, compose the answer) — NOT a fixed set, so rules break on unseen forms. **Claude owns this.** Rules + local qwen are a *fast-path* for the obvious (name, email, plain yes/no) so Claude's attention/cost goes only to the ambiguous/novel.

Every field-tag bug we hit (address="Yes", middle-name, search-box fill, "Continue Working"-as-advance) was a deterministic-interpretation failure — evidence interpretation can't be a rulebook.

## 3. Invocation — a scheduled Claude session, hourly

The **dashboard attaches an hourly schedule** that, per new job, runs the agent. When Claude drives (a Claude session, e.g. a routine), it supplies interpretation + `vision_fn`. When the run is plain Python (qwen only), `vision_fn=None` and DOM-unlabeled fields degrade to escalation — graceful, not broken.

## 4. Perception — faithful extract, not the lossy guesser

- Field labels come from the **W3C accessible-name priority** (aria-labelledby → aria-label → `<label for>`/wrapping → legend → title; sibling/container fallback; placeholder last), plus the **accessible description** (`aria-describedby`). *Built (commit 8ef7de9).*
- Every field gets a **unique `data-cref` handle** so it's addressable even with no id/name (custom widgets shared `[name=""]` before). *Built (d59b42c).*
- **Vision fallback:** when a field is genuinely unlabeled in the DOM (`is_unlabeled`: empty / placeholder-only "Start typing…"/"Pick date…"/"Select…" / a checkbox whose only text is "Yes"/"No"), perception screenshots the page + the fields' boxes and asks `vision_fn` (the orchestrating Claude reading the shot) for the real question; `apply_vision_labels` applies them and re-guesses purpose. *Built (7233f3b); live-proven on Ashby.*
- Interpretation LEAVES perception — the regex `guess_purpose` is a fast-path only, not the decider.

## 5. JD source

Primary: the **jobs table by job_id** (the dashboard already scrapes ~13k JDs into `jobs.description`; `get_job(conn, job_id)`). The routine drives from the queue so it has `job_id → url → description` together — no re-scraping. Fallback (off-board/pasted URL, no job_id): **generic readability main-content extract** (not raw innerText), **cached back** to the table so it's stored next time. The JD's company description is a first-class input to both matching and customization (§6).

## 6. Answering & recall — semantic retrieval + customize

A field is answered by fetching from stores, in priority order:
1. **Learned/corrected answer** (recall) — checked FIRST so it also **overrides** a rule that would fill wrong (see §7). 
2. **Profile fact** (rules) — name, email, demographics, location, links (from `application_profile`).
3. **qwen** (judge) — enum mapping, short factual free-text.
4. **Escalate** to the human (the live-view / Telegram) — then write back.

**The recall store is a first-class answer source in every normal run** — it's how the agent answers questions no profile field covers ("notice period", "how did you hear", custom Qs). Read = recall; write = feedback.

**Company-specific essays ("why this company") — the semantic approach:**
- Store each approved answer **generic** (company name stripped) with its context (question + JD gist).
- For a new question, **embed (the scraped JD + question)** and fetch the **semantically-closest past answer** — no manual company-type taxonomy; the embedding of an AI JD lands near your past AI answers on its own. The vector DB never needs to "know" the company; the company-ness lives in the query, built from the already-scraped JD.
- **Claude customizes** that generic answer using the JD's company description for **tone + direction** — the company info is a *tailoring signal, not a storage key*. So the generic core is cached; the company veneer is generated fresh each time (resolving "never cache company-specific").
- **Scale threshold for the vector DB:** early (few past answers) → hand Claude *all* of them + the JD, it picks+customizes (fits in context, no infra). Later (many) → vector retrieval fetches the top-few closest. Same design; vector kicks in only when the answer-pile outgrows the context window. Profile facts and the knowledge repo still fit in context and need no retrieval.

**Boundary:** truly company-specific answers are never stored as-is; only generic/semantically-reusable cores are. Universal facts are cached verbatim; essays are composed/customized, never blindly reused.

## 7. Feedback — read-back diff, recall-first priority

- **Capture:** after the human edits (on the live-view, §8), the agent **reads back every field** and **diffs** against what it filled (`A = agent fill {ref/question: value}`, `B = final {…}`, `corrections = {q: B[q] for q where B≠A}`). No need to be told what changed — the diff is the feedback. *(read_back already exists.)*
- **Store:** each correction is written to the recall store keyed by the **question** (generic; scope-agnostic via semantic match). 
- **Priority — the make-or-break:** recall must run **first/high-priority** so a learned correction **overrides** the rule/qwen that got it wrong. Today the order is `rules → judge → recall → human`; it must become `recall(corrections win) → rules → judge → human`. Without this, `address="Yes"` repeats forever.
- **Boundary:** essays (textareas) are excluded from verbatim feedback — only stable factual answers/corrections learn; essays feed the generic-answer store per §6.

## 8. Human surface — the interactive Tailscale live-view

The single review/edit/submit surface is the **interactive live-view** (extends the captcha relay), delivered via Telegram:
```
agent fills the live form (real-time)
  → sends the Tailscale live-view link to Telegram
  → you open it on your phone: see the FILLED form, tap a field, retype it,
    fix the essay, tap Submit — directly on the real form
  → agent reads back the final values → diffs vs its fill → writes corrections (§7)
```
**Build required:** the live-view is currently **tap-only** (forwards pointer events for captcha). Add **keyboard input** — a text-entry path on the phone page + CDP `Input.dispatchKeyEvent`/`insertText` into the focused field — so the mirror becomes a full remote control (tap + type). This is the one non-trivial new build; it collapses captcha + edit + submit + feedback onto one screen and avoids tedious `"N: value"` prompting.

**Why not Telegram text-prompt editing:** prompting each change is slow; direct manipulation on the mirrored form is faster and needs no edit grammar. Telegram just delivers the link + notifications.

## 9. Human-in-the-loop — two lanes

A captcha link/session dies in minutes (`remote_solve_ttl`=300s; the live page closes when the run ends; Oracle app is bound to the live session — re-nav 404s). So a captcha **cannot be parked-and-resumed** — only solved live during a run.
- **Lane A — captcha-free** (Greenhouse/Ashby/Lever, no login): filled fully unattended; **parked at SUBMIT** for review. Because these forms have **no bound session**, the review/edit can happen later — the agent re-opens, applies the final answers, submits. The bulk.
- **Lane B — captcha/login** (Oracle-class): only doable while the browser is open and the human is present → **batched for a supervised burst**. Review/edit/submit happen **live, in the same session** (can't re-open). A run that hits a captcha with no one present marks the job "needs live session", moves on, and restarts it fresh later.
- **Essays park fine** (just text). **Captchas do not.**
- **Real-time fill always; real-time EDIT only where the session forces it** (Lane B); Lane A edits can be deferred.

## 10. Boundaries (unchanged, hard)

Agent NEVER solves captchas (relay to the human), NEVER creates accounts or enters passwords, NEVER auto-submits except on explicit command; SUBMIT is always the human consent point; PII stays local (qwen local; Gmail OTP read is the one user-authorized exception — prefer a direct IMAP/app-password in unattended runs over the interactive MCP connector, which may be absent in cron).

## 11. Build inventory

**Built this session (branch `career-agent-demographics`, 185 tests, live-proven):** demographics/attestations autofill · React-combobox open+pick fill · learning loop (recall/record, SQLite+FTS5) · Telegram collector (editable essay drafts, drain, clear messages) · essay routing (escalate, not auto-fill) · address/middle-name/`\brole\b` tag fixes · signal-based closed-posting skip · accname perception + descriptions · reliable apply-hop (ATS URL fallback) · vision fallback · unique `data-cref` refs.

**To build (this spec):**
1. **Interactive live-view** — keyboard input in the CDP bridge (§8). *The one big piece.*
2. **Read-back diff feedback** — capture corrections from the live-view, write to the recall store (§7).
3. **Recall-first ordering** — recall/corrections override rules (§7).
4. **Semantic generic-answer store + customize** — store generic answers, closest-match fetch (all-in-context early; vector later), Claude customizes with JD company info (§6).
5. **JD readability fallback + cache-back** (§5).
6. **Two-lane submit orchestration** — Lane A defer/re-open, Lane B live (§9).
7. Minor polish: dedupe react-select duplicate inputs; guard name-labelled checkboxes; preferred-name ≠ full-name.
