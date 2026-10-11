# 2026-10-11 — Making the apply agent finish a Zoho Recruit form (Wadhwani AI, job 450)

## Goal
Job 450 (Himalayas → Wadhwani AI on Zoho Recruit) stopped every time with "no advance control", 0 fields filled.
Walk the run step by step against full-page screenshots, find what the agent can't see, and fix it generally.

## What was wrong, run by run (each found from the screenshot, not the log)
1. **Reach**: "I'm interested" opens the form in place, but Zoho's inputs have no programmatic labels
   (`name="rec-form_<id>"`; the question lives on the wrapper as `cx-prop-label`). Reach counted 0 applicant fields,
   tried `<url>/apply`, which reloaded the job page. Fix: read wrapper label attributes (`page_prep`, `perception`);
   never guess a URL away from a page with ≥3 fillable fields.
2. **Labels**: wrapper labels, attribute order (skip `lt-prop-label="value"`), only from a wrapper of that one field;
   a `<label>` beside the field's wrapper (after a tick box, before anything else; keep the end of a long statement).
   Duplicated ids (`id="inputId"` ×4, the first a hidden dial-code search) made Zip/City/State type into the hidden
   box: an id is a ref only when unique. Each scan clears the previous scan's `data-cref` stamps (two elements
   carried `f23`). A suggestion popup inside a text box's widget is not a second field.
3. **Facts**: the free-text tier got almost nothing about the candidate (an empty legacy résumé-layout table; default
   version named after someone else) and wrote "about 0.5 years of experience" from essay snippets. Now
   `grounding_text`: saved profile facts first, then the résumé text. "How many…", "(in days)", "(in LPA)" questions
   get a number or go to the user (`judge_number`); durations convert to the asked unit ("1 month" → 30); "City"
   gets the city alone; "…years… degree" is not the degree question.
4. **Uploads**: the résumé also went into Zoho's résumé-parsing "Autofill" box, which rewrote LinkedIn; and after an
   upload the agent kept whatever the site's parser wrote. Now the parsing uploader is skipped when a real
   "Upload résumé" field exists, and our saved values overwrite parser guesses. A hidden file input inside a visible
   upload widget is a field.
5. **Writes that don't stick**: Zoho's tick box never counts as clickable (forced click fallback); the consent
   section re-renders after ticking, wiping the signature. After filling, every text value is read back; a blank or
   vanished one is re-found by label and retyped with keystrokes; what still fails is logged by name.
6. **Small**: "Please provide your consent" is an attestation; only file inputs are résumé uploads; optional
   non-question boxes ("Additional Info") are left empty, not escalated; a run stuck on the user's questions ends
   as `needs_answers`, not `error`.
- Also removed a hard-coded "Rakshit Singh" (account-creation fallback name, résumé PDF title, default résumé
  version). Account names come from `.env` or the saved profile.

## Result
Run 1: 0 filled, stopped. Run 5: 20 filled and correct on screen; left for the user: Street (no address saved),
hands-on LLM years (nothing on file supports a figure), CAPTCHA (always the human's). Not submitted.

## Verified
Full pytest 1561 passed; career_agent 555; five live dry runs (`--review --no-telegram`) with screenshots.

## Open
- `data/current_resume.pdf` is a 2023 student résumé with no Adobe role; it is what employers receive.
- perception.py / page_prep.py / credential_provider.py were already over 500 lines and grew slightly; split them.
- Hill-climbing over many jobs needs a current résumé, target roles and the user's go-ahead to submit.
