# Career Agent — Page-Prep Toolkit & Application Entry (Design)

**Status:** Approved 2026-08-29
**Branch:** `career-agent-page-prep` (off `career-agent-phase-e`)
**Depends on:** the career agent walk (`step_engine`, `perception`, `browser_deps`), Phase-2 remote-solve (captcha phone-relay), the Gmail-OTP orchestration validated on JPMorgan this session.

## Motivation

Live testing showed the walk fails or mis-fills before it even reaches a real form, on obstacles that recur across sites:

- **Company/JD pages** (retransform): a cookie "OK" overlay + no inline form; the apply is one click away or elsewhere.
- **Oracle**: an idle **session dialog** ("Continue Working") and an **ODA chatbot** whose textareas ("Ask Me Something") pollute the Form Model; plus **honeypot** and **captcha-token** fields perceived as real.
- **Enterprise portals** (JPMorgan): the application is behind an **email-first auth** step (enter email → captcha → OTP → form) — already solved ad-hoc this session (email fill + phone-relay captcha + Gmail-OTP read), but not reusable.

These are one-off hacks in scratch drivers today. This spec makes them **small, reusable, tested tools** the walk composes.

## Goal

A reusable **page-prep toolkit** that (a) clears blocking overlays/dialogs and perception noise, and (b) gets the walk from a landing URL to the actual application form — recognizing the two real shapes an application takes: **direct form** or **email-first auth** — while holding the credential boundary on account creation.

## The two shapes (entry classification)

Every real application, after any "Apply", is one of:

1. **Direct form** — a fillable form is present → walk it.
2. **Email-first auth** — an email-entry / "continue with email" screen (JPMorgan-style, passwordless: email → maybe captcha → OTP → form). The agent handles this end-to-end.
3. **Password / account-creation** — a visible `input[type=password]` or "create a password" / "sign in with password". **The agent never fills a password.** It stops and hands off (password-manager autofill if present, else a one-time human step), then resumes in the same authenticated session.

## Global Constraints (boundaries)

- **No agent-entered passwords / account creation.** The agent NEVER types into a password field or creates a credentialed account, regardless of instruction. Password screens → password-manager autofill (the manager enters it, not the agent) or human hand-off; the agent never sees/handles the secret.
- **Consent is not attestation.** `dismiss_consent` acts only on **site cookie/consent overlays** (decline-preferring; OK/Accept only to unblock). It NEVER ticks an application **T&C / attestation / e-signature** — those remain never-auto-ticked.
- **Captcha unchanged:** detect + escalate (phone relay); the agent never solves it.
- **OTP:** read via an injectable `otp_reader` (the orchestrator/Gmail, as validated this session); the agent enters the code but never the password.
- **Dry-run / human-gated submit unchanged.** Nothing here submits.
- **Idempotent & safe:** every prep tool is a no-op when not applicable and never clicks a destructive/submit control.
- **LLM-free.** No model calls in this toolkit.
- Branch `career-agent-page-prep`; commit per task.

## Components — `browser/page_prep.py`

1. **`dismiss_consent(page) -> bool`** — locate a cookie/consent overlay (role=dialog or a banner with consent text); click **Decline / Reject / Only necessary / Manage → reject** if present; else **OK / Accept / ×** to unblock. Never a control inside an application form (guard: skip if the page's main content is a form / the button sits inside a `<form>` with real inputs). Returns True if it dismissed one.

2. **`dismiss_dialogs(page) -> bool`** — dismiss transient/idle modals that block the form: "Continue Working", "Continue", "Stay", "Dismiss", "×" on a `[role=dialog]`/`[role=alertdialog]`. Never "End Session"/"Discard"/"Submit"/"Delete". Returns True if it dismissed one.

3. **`suppress_noise(fields) -> fields`** — pure Form-Model filter (list[Field] → list[Field]): drop chatbot fields (`ref`/label match `oda-`, "ask me something", "add summary"), honeypots (name/id/label match `honey`), and captcha-token textareas (`g-recaptcha-response`, `h-captcha-response`). Never drops a field with a known purpose or a normal label.

4. **`classify_entry(page) -> str`** → `"form" | "email_auth" | "password" | "none"`:
   - `"password"` if a visible `input[type=password]` OR page text ~ "create a password" / "sign in".
   - `"email_auth"` else if a visible email input AND text ~ "verify"/"one-time"/"we'll send"/"continue with email"/"create ... profile".
   - `"form"` if ≥2 fillable non-search inputs are present.
   - `"none"` otherwise (a JD page / nothing actionable).

5. **`enter_application(page) -> str`** — when `classify_entry(page) == "none"` and an Apply control exists (button/link: "Apply", "Apply now", "Apply for this job", "I'm interested", "Start application"), click it **once**, follow a same-tab nav or **adopt a new tab** (return the active page), then return `classify_entry(...)` of where it landed. One hop — if still `"none"`, return `"none"` (report; don't chase).

6. **`email_auth(page, email, otp_reader, on_captcha) -> str`** — for the `email_auth` shape: fill the email input with `email`; if `classify_gate(page)` is an interactive captcha → `on_captcha(page, gate)` (phone relay); click Next/Continue; if an OTP screen appears → `code = otp_reader()` (injectable; None → return `"otp_timeout"`), fill the code boxes, submit; return `classify_entry(page)` (`"form"` on success). Never fills a password; never ticks T&C (the human taps it via the relay, as validated). Reuses the 6-box OTP fill + `classify_gate` from this session's Oracle work.

## Wiring

- **`prepare(page) -> None`**: runs `dismiss_consent` then `dismiss_dialogs` (both idempotent) — called at the **top of each walk step**.
- **`suppress_noise`** applied inside perception (`snapshot_form` / `to_form_model`) so every consumer (mapper, judge, walk) sees a clean Form Model automatically.
- **`step_engine.walk`** gains a `prep_fn=None` param (mirroring `judge_fn`): when set, `prep_fn(page)` runs before `deps.snapshot`.
- **Entry orchestration** (in `apply.py`, before the walk): loop `classify_entry` → `enter_application` (once) → dispatch: `"form"` → walk; `"email_auth"` → `email_auth(...)` then walk; `"password"` → print a clear STOP ("log in / create the account in the open browser or via your password manager, then press Enter") and, on resume, continue the walk in the same session.
- `otp_reader` / `on_captcha` are injected in `apply.py` (orchestrator file-signal for OTP as validated; remote-solve factory for captcha). Absent → email_auth degrades to escalate/stop.

## Data Flow

```
apply.py: goto(url) ─► prepare(page)
   loop: classify_entry(page)
      "none"       ─► enter_application(page)  [one Apply hop] ─► re-classify
      "form"       ─► walk(page, ..., prep_fn=prepare, judge_fn=...)   # dry-run
      "email_auth" ─► email_auth(page, email, otp_reader, on_captcha) ─► walk
      "password"   ─► STOP + human/password-manager, then ─► walk in-session
perception.snapshot_form ─► suppress_noise ─► clean Form Model (everywhere)
```

## Error Handling

- Every tool never raises on a missing element (returns False / "none").
- `enter_application`: one hop only; no form → "none" (no infinite chase).
- `email_auth`: captcha not solved → stop (`gate:*`); OTP timeout → "otp_timeout"; never a password.
- `password` shape → never auto-handled; always human/manager.
- A consent/dialog tool never clicks a control inside a real form or a submit/destructive action.

## Testing

**Unit (pure):** `suppress_noise` — drops oda/honeypot/captcha-token fields, keeps real ones.

**Browser (fixtures, RUN_BROWSER_TESTS):**
- `dismiss_consent`: a banner with "Decline" → declined (returns True, banner gone); an accept-only banner → "OK" clicked; a page with a real form and no banner → no-op (False).
- `dismiss_dialogs`: a `[role=dialog]` with "Continue Working" → dismissed; a form page → no-op.
- `classify_entry`: fixtures for form / email-auth (email + "verify" text) / password (`input[type=password]`) / none (JD page) → correct label.
- `enter_application`: a JD fixture with an "Apply" button revealing a form → returns "form".
- `email_auth`: a fixture email→(no captcha)→OTP screen with a fake `otp_reader` returning "123456" → fills, returns "form".

**Live re-validation (dry-run):** retransform (company page: consent dismissed, Apply followed or reported), Rippling (noise-free perception), and a live JPMorgan Oracle job (email_auth: email → phone captcha → Gmail OTP → form) — nothing submitted.

## Out of Scope

- **Solving captchas** (unchanged: detect + phone-relay).
- **A standalone Python Gmail-API client** — OTP stays via the injectable `otp_reader` (orchestrator/Gmail file-signal, as validated); a direct client is a later item.
- **Multi-hop apply chains** beyond the single Apply hop + the email-auth/password branch (the two real shapes cover the rest).
- **Agent-created accounts / agent-entered passwords** — permanently out of scope (boundary).
- **Per-ATS bespoke adapters.**
