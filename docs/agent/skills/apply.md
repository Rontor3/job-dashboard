---
description: Run one job application end to end: open it, fill every page from the user's own data, then submit, pause or skip
---
# Apply to one job

You own this application. The app is your harness: the tools read the page for you as a list of fields, write what
you decide, and tell you what didn't take. Work page by page until the run ends in exactly one of: **submitted**,
**paused** (the user must act), or **skipped** (a wall). Every run ends in one of those three. Never stop halfway
without one.

## The loop

1. `apply_start(job_id)`. It tells you the board or site, and the job's **priority**.
   - If it says `skipped`, the run is over. Say why in one line and stop.
   - If it says `resumed`, the tab is where the run paused, and the user may have answered questions since. Go to step 3.
   - If you know the board (LinkedIn, Wellfound, Himalayas), `load_skill` that board's skill.
2. `apply_reach(job_id)` gets you to the form.
   - `skipped`: stop.
   - `on_form: false`: read `apply_page_text` and look for what the page wants.
3. `apply_snapshot(job_id)` lists the page's fields. Each field may have a **suggestion** taken from the user's own data.
4. Decide every field you'll fill, then make **one** `apply_fill` call:
   - **Suggestions:** take them with `accept_suggestions: true`. Override a suggestion only when it plainly doesn't
     answer the question.
   - **Fields without a suggestion:** look up the user's data. Use `get_profile`, `read_resume`, `search_answers`
     (saved answers), `get_ingredients` (projects and achievements, quoted as written), and `get_job` (the job
     description).
   - **Grounded values:** give `source` and an exact `citation`, for example `profile.notice_period`, or
     `résumé: Experience, Acme 2021-24`.
   - **Choice fields:** pick one of the field's own options. Choose the option that matches a grounded fact, and use
     `source: "option"` with that fact as the citation.
   - **Questions only you can compose** (a short "why this company", a cover note): write it from the résumé and the
     job description, honestly and in the user's voice, with `source: "agent"`. The user sees these as written by
     you, not their words. Never invent experience, numbers, employers or dates.
   - **Leave out:** optional fields you have nothing grounded for. Sensitive fields (marked `sensitive`) are never filled.
   - **Files:** a résumé field takes `value: "resume"`.
5. Read what `apply_fill` returns, and fix each problem with one more `apply_fill`:
   - `rejected`: you broke a rule, so fix the answer (usually a missing citation).
   - `did_not_stick`: the page refused the value. Try the option's exact text, or a shorter value.
   - `required_empty`: a required field is still blank. Answer it if you can ground it.
6. **A required question you can't ground and shouldn't compose** (a salary they never gave, a yes/no about their
   history, a legal attestation):
   - fill everything else first;
   - then `apply_pause(reason: "needs_answers")` with those fields as `questions` (each with `why`), and a one-line
     `detail` saying where the form stands. Stop.
7. When the page has a `next` control, call `apply_advance` and go back to step 3.
8. On the last page (`submit` is set, `next` is not), call `apply_submit`.
   - `held`: call `apply_pause(reason: "review", detail: <the reasons, in plain words>)`. Never retry a held submit.
   - `submitted`: say so in one line and stop.

## Dialogs over the page

After every step, the harness looks for a dialog. Cookie banners and "are you still there?" prompts are cleared for
you; a sign-in dialog or a captcha ends the run as skipped. Any other dialog comes back in the step result as
`dialog` (kind, title, text, buttons). Answer it before anything else:

- **`apply_step`** ("I'm ready to apply", "Apply on company site"): press the button that continues the application.
- **`question`**: read the text and choose with `apply_dialog`, using the button's exact text.
  - A choice the user's data answers (location, "are you authorised to work in…"): pick the matching button.
  - A referral or promo-code prompt, a newsletter or "join our talent community": take the option that commits the
    user to nothing new. Decline a code they didn't give you; close the dialog if that is all it offers.
  - A choice that commits the user to something new or that you can't ground (terms, a paid plan, sharing data with a
    third party): pause with reason `needs_answers` and quote the dialog in `detail`.
- **If the dialog has its own fields:** take a snapshot, fill them with `apply_fill`, then press its button.

## Walls you never cross

- **A captcha or bot check:** `apply_skip(reason: "captcha")`. Never try to solve one, click through it, or get around it.
  That includes a captcha typed into a plain box (a field labelled "CAPTCHA" or "type the characters"): skip, don't
  pause for the user.
- **A sign-in or sign-up page:** `apply_skip(reason: "account_needed")`. Never create an account or type a password.
- **A required bank or ID detail** (account number, PAN, Aadhaar, passport, SSN): `apply_pause(reason: "sensitive_field")`.
- **The job isn't one the user can take** (location they can't work in, a closed posting): `apply_skip` with the reason.

## Priority

- `high` and `dream` jobs matter most to the user. Answers you wrote yourself will hold submit for their review, so
  write those answers with extra care.
- At `low` and `normal`, those answers go out marked as yours.

## Staying on track

- **Repeated failures:** if a page doesn't change after two `apply_advance` calls, read `apply_page_text` once. If
  you still can't see a way on, `apply_pause(reason: "stuck", detail: what you saw)`.
- **Too many steps:** if you've made more than about 40 tool calls in this run, pause with `stuck`.
- **The final line:** one sentence for the user. Name the company and role, say submitted / paused / skipped, and say
  what they need to do, if anything.
