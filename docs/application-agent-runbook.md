# Application Agent — Side B Runbook (browser fill)

This is the procedure the **browser agent** (the assistant, using the
Claude-in-Chrome tools) follows to fill a job application in the user's own
Chrome and **stop at Submit**. It is a runbook, not app code. Side A (the
dashboard) has already produced the answers; Side B only *places* them.

## Hard stops (non-negotiable — restated from the spec)

The agent MUST NOT, under any circumstance:

1. **Click Submit / Apply / Confirm / "Send application"** — or any control that
   finalizes the application. Fill, then stop and hand back to the user.
2. **Enter a password, create an account, or solve a CAPTCHA.** If the site
   requires login, signup, or a CAPTCHA, STOP and tell the user — they do it.
3. **Invent an answer.** Only place values that came from Side A (the
   application profile, the resume/cover-letter, or a screening answer the user
   already reviewed). A field with no confident mapping is **left blank and
   reported**, never guessed.
4. **Touch EEO / demographic / disability / veteran** questions — leave them
   untouched for the user.
5. **Navigate off the given job URL.** Act only on the page the user handed over;
   never follow other links.

If any hard stop is hit, pause, report exactly what's blocking, and let the user
act.

## Preconditions (check before starting)

- The Claude-in-Chrome extension is connected (`mcp__claude-in-chrome__*` tools
  available). If not, ask the user to connect it.
- The user has filled their **application profile** in the dashboard
  (`GET /api/application-profile` returns data, not `{}`). If empty, stop and ask
  them to fill it first.
- The user has explicitly given the **job URL** and said to apply to it.

## Procedure

1. **Fetch the answers from Side A** (the local dashboard API):
   - `GET /api/jobs/{id}/application-package` → `{profile, resume, cover_letter,
     job, ats_hint}`.
   - `GET /api/ats-map/{ats_hint}` → the field-map (label synonyms per intent).
     If `ats_hint` is `generic`, use `GET /api/ats-map/generic`.
2. **Open the job URL** in the user's Chrome (`navigate`). Read the page
   (`read_page` — accessibility tree). Confirm the detected ATS; if the page is a
   login / account-creation / CAPTCHA wall → **hard stop #2**, report.
3. **Map and fill the standard fields.** For each form field, match its
   label/placeholder against the field-map's synonyms to an intent, then fill the
   matching profile value (`form_input` / `computer` type):
   - full_name, email, phone, location, LinkedIn, GitHub/portfolio → from
     `profile`.
   - **Resume**: upload the resume PDF (`resume.pdf_path`) into the resume/CV
     file field. (Use the file-upload path appropriate to the page.)
   - **Cover letter (OPTIONAL)**: only if the form has a cover-letter slot AND
     `cover_letter` is present AND the user opted in — attach/paste it. No slot →
     skip. Never force one.
   - **work authorization / sponsorship** questions → answer from
     `profile.work_authorization` (the user's real status). If the phrasing is
     ambiguous, leave blank and flag.
   - Any field you cannot confidently map → **leave blank, add to the flagged
     list**.
4. **Screening free-text questions.** For each free-text question on the page:
   - `POST /api/jobs/{id}/screening-answer {question}` → `{answer, flags}`.
   - **Show the draft to the user and let them edit** before filling. Then place
     the (possibly edited) text.
5. **STOP at Submit** (hard stop #1). Do not click the final control.
6. **Report** to the user, plainly:
   - fields filled (with the values placed),
   - fields left blank / flagged (and why — unmappable, ambiguous, EEO, needs
     login/CAPTCHA),
   - the explicit reminder: *"I've stopped at Submit — review everything and
     click Submit yourself."*
7. **After the user submits**, on their confirmation, record it:
   `POST /api/jobs/{id}/application {resume_id, cover_letter_id (or null),
   screening: [...], ats, status: "applied"}`. The dashboard marks the job
   applied.

## Notes

- Prefer the field-map for known ATS (Greenhouse/Lever/Ashby/Workday); fall back
  to `generic` label matching elsewhere, and be more conservative about leaving
  fields blank when unsure.
- The two review gates are: (1) the user approved the package in the dashboard
  before step 1; (2) the user reviews the filled page before *they* submit at
  step 6–7. Never collapse these.
