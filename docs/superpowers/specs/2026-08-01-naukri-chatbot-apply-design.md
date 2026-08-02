# Naukri Chatbot Apply — Design

**Date:** 2026-08-01
**Status:** Approved (design), pending spec review
**Depends on:** Application Agent (`apply/` package), screening grounding guard

## Goal

Extend the existing browser Application Agent to handle Naukri's **conversational
chatbot apply**, in a **hybrid** shape:

1. **Résumé push (NopeRi, headless):** before applying, push the job's tailored
   résumé PDF to the candidate's Naukri **profile** via NopeRi's `update_resume`,
   then **read-back-verify** the new résumé is live (Naukri processes uploads
   asynchronously — applying before it lands would send the old file).
2. **Apply (browser, visible):** the agent drafts grounded answers to Naukri's
   chatbot screening questions from the stored profile + résumé, presents the
   full answer set for review, and **stops before the candidate sends the final
   message**.

Confirmed live (2026-08-02): clicking Apply on a typical Naukri job opens a
**chatbot** ("How many years of experience do you have in Artificial
Intelligence?"), one question at a time, with no per-job résumé-upload control —
so the profile résumé is what gets sent, which is exactly why the push step
exists. Naukri **ingest/search** stays read-only and untouched.

## Non-goals

- No one-click instant-apply automation (agent stops the user *before* an
  irreversible instant-apply; it does not click it).
- No "Apply on company site" handling — those redirects already fall through to
  the existing ATS agent.
- **No programmatic apply via NopeRi.** The résumé *write* (`update_resume` +
  its `validate_file`/`fetch_profile_id` dependencies) is now imported on
  purpose; NopeRi's apply / questionnaire / auto-apply-agent code is **still
  never imported**. The apply itself happens only in the browser.
- No change to the read-only Naukri **source** (`sources/naukri_source.py`).
- No auto-submit, ever. The candidate sends the final chatbot message.

## Boundary change (explicit)

The original Naukri boundary was "read-only — never import any NopeRi write
code." This spec **consciously narrows** that: NopeRi's **résumé-update** path is
now in scope (the candidate opted in — it is the only way to attach a per-job
tailored résumé on Naukri's uploadless chatbot flow). The write surface is
isolated to one module (`apply/naukri_resume.py`) and is limited to
`update_resume`; programmatic **apply** stays out. Risk accepted: `update_resume`
hits Naukri's private profile API, so a Naukri-side change could make it misfire
or no-op — mitigated by the mandatory read-back verify before any apply.

## Architecture

Naukri apply is a new **branch of the existing Application Agent**, not a new
subsystem. Four pieces:

1. `apply/naukri_resume.py` — the **résumé push**: `push_resume(pdf_path,
   session_path, verify=True)` wraps NopeRi's `update_resume` + a read-back
   verify. The **only** module that imports NopeRi write code. Never raises;
   returns a structured result the runbook gates on.
2. `apply/naukri_answers.py` — the **resolver**: classify each chatbot question,
   route to profile / grounded-draft / blank. Pure logic, no browser, never raises.
3. `apply/store.py` — extend the single-row `application_profile` with the two
   missing Naukri personal-fact fields.
4. `docs/naukri-apply-runbook.md` — the **browser procedure** that drives the
   candidate's real Chrome (same tools used for the Wellfound/Workday live runs);
   no new automation code.

Detection: the browser runbook checks the job host. `naukri.com` + chatbot apply
→ Naukri handler; "Apply on company site" → existing ATS flow; anything else →
existing flow. Detection lives in the runbook (a human-followed procedure), not
in a new code path, because the existing agent already branches by host in the
runbook.

## Data model — stored personal facts

The `application_profile` single row **already has** `notice_period`,
`willing_to_relocate`, and `salary_expectation`. Reuse `salary_expectation` as
**expected CTC**. Add only the two genuinely missing fields:

- `current_ctc TEXT` — current compensation (free text, e.g. "12 LPA").
- `reason_for_change TEXT` — short reason-for-change blurb.

Both nullable. Added to `application_profile` via a `CREATE TABLE` column list +
idempotent `ALTER TABLE ... ADD COLUMN` guard (matching the `duplicate_of`
column pattern in `db.py`), and appended to `_PROFILE_COLS` so the existing
`get_/save_application_profile` round-trip them with no other change.

Unset field → resolver returns **blank + flag** (`needs_user=True`). A personal
fact is **never** sent to the LLM and **never** guessed.

## Résumé push — `apply/naukri_resume.py`

The only module that imports NopeRi write code, and only these three symbols:
`NaukriLoginClient` (to restore the cached session, as the source already does),
`update_resume`, and its internal `validate_file`/`fetch_profile_id` (pulled in
transitively by `update_resume`). NopeRi's apply/questionnaire modules are never
imported here.

```python
@dataclass
class PushResult:
    ok: bool
    live_resume_name: str | None   # what Naukri reports as the active résumé after push
    error: str | None              # set when ok is False; never raises

def push_resume(pdf_path, session_path=DEFAULT_SESSION_PATH, verify=True,
                client_factory=None) -> PushResult
```

Flow:
1. Restore the cached Naukri session (reuse the source's `_default_client_factory`
   pattern; `client_factory` injectable for tests). No session / unreadable →
   `PushResult(ok=False, error="no_session")`.
2. `client.update_resume(pdf_path)` → inspect the returned `ResumeUpdateResult`
   status. Non-2xx → `ok=False, error="upload_rejected"`.
3. **Read-back verify** (when `verify=True`): re-fetch the profile résumé name
   and confirm it matches the pushed file's basename. Naukri processes uploads
   asynchronously, so poll a small bounded number of times (e.g. 5 × 2s) before
   giving up with `ok=False, error="verify_timeout"`. Only `ok=True` authorizes
   the runbook to proceed to Apply.
4. Any exception (blocked, token expired, API shape change) is caught →
   `PushResult(ok=False, error=type(exc).__name__)`. **Never raises** (parity
   with the read-only source).

The runbook **must** treat `ok=False` as a hard stop — it never applies with an
unverified résumé (that is the "sends the old file" failure mode).

## The resolver — `apply/naukri_answers.py`

```python
@dataclass
class AnswerResult:
    text: str            # "" when unanswered
    source: str          # "profile" | "resume" | "unanswered"
    needs_user: bool     # True => blank, candidate must fill/confirm
    flag: str | None     # e.g. "no_stored_value", "grounding_failed", "unknown_question"

def classify_question(question: str) -> str:
    # returns "personal" | "groundable" | "unknown"

def resolve_answer(question: str, package: dict, llm=None) -> AnswerResult
```

**`classify_question`** — deterministic keyword/pattern match first:

- **personal** — matches CTC / salary / compensation / "lpa", notice period,
  relocat*, "reason for (change|leaving|switch)". (A "current company" question
  is **not** personal — it is on the résumé, so it routes as groundable.)
- **groundable** — "years"/"experience"/"how many"/"know"/"proficient"/"worked
  with" + a skill token, "current location", "willing to work"/"comfortable
  with" (shift/onsite/etc.).
- **unknown** — no match.

An LLM tie-break is **not** in v1 (YAGNI): unmatched → `unknown` → blank+flag.
Keeps classification fully deterministic and testable; the human fills anything
the table doesn't recognize.

**`resolve_answer`** routes on the class:

| Class | Route | Result |
|-------|-------|--------|
| personal | look up the mapped profile field | stored value → `text`, `source="profile"`; unset → blank, `needs_user=True`, `flag="no_stored_value"` |
| groundable | `draft_screening_answer(job, question, profile_text, research=None, resume_text)` then inspect its result | grounded answer → `text`, `source="resume"`; if `unsupported_company_claims` non-empty OR `general_fallback` → blank, `needs_user=True`, `flag="grounding_failed"` |
| unknown | none | blank, `needs_user=True`, `flag="unknown_question"` |

Personal-field mapping (question class → profile key):
current CTC → `current_ctc`; expected CTC → `salary_expectation`; notice →
`notice_period`; relocate → `willing_to_relocate`; reason → `reason_for_change`.

`research=None` is passed to `draft_screening_answer` (Naukri answers are not
company-pitch questions), so the prompt supplies **no** company facts and the
grounding guard treats any company-specific claim as unsupported — exactly the
safe default. The resolver **never raises** (mirrors `draft_screening_answer`).

## Data flow (browser run, per runbook)

1. Candidate clicks **Apply (Naukri)** on a card → `assemble_application_package`
   (existing) builds `{profile, resume, cover_letter?, job}`.
2. **Push + verify (NopeRi, headless):** `push_resume(resume.pdf_path)` uploads
   the tailored PDF to the Naukri profile and read-back-verifies it is live.
   `ok=False` → **stop and report**; do not open Apply. Skipped only if the
   candidate has no tailored résumé for this job (falls back to whatever profile
   résumé is already live).
3. Agent opens the Naukri job in the candidate's **real Chrome** (logged-in
   session), clicks Apply; the chatbot appears.
4. For each visible question: agent reads the text → `resolve_answer` → collects
   `AnswerResult`s.
5. Agent presents the **full list** — question → drafted answer → `source`, with
   `needs_user` items clearly flagged as blanks the candidate must fill.
6. Candidate approves/edits, then **sends the final message themselves**.
7. **Fallback:** if Naukri hides Q2 until Q1 is sent (draft-all impossible) — the
   confirmed live behavior — the agent switches to **answer-then-pause per
   question**: fill one, wait for the candidate's go, never sending the last one
   automatically.

Note: the chatbot flow has **no per-job upload control** (confirmed live), so the
résumé reaches the employer via the profile push in step 2, not an in-chat
upload. If a given job *does* show an upload control, the agent uses it directly
and step 2 can be skipped.

## Error handling

- **Résumé push fails or can't verify** (`ok=False`) → **hard stop before Apply**;
  report the `error`. Never apply on an unverified résumé — that is the
  "sends the old/wrong file" failure mode the push exists to prevent.
- Not logged in / no Naukri session → push returns `no_session`, Chrome apply
  step also stops and tells the user.
- Unrecognized chatbot variant → agent stops and hands over the keyboard; never
  blind-fills.
- LLM unavailable → groundable questions blank+flag (`grounding_failed` via the
  `general_fallback` path); personal facts unaffected (never LLM'd).
- No stored personal answer → blank+flag; nothing invented.

## Testing

Unit (`tests/test_naukri_answers.py`):

- `classify_question` over a table of real Naukri strings → correct bucket
  (CTC, expected CTC, notice, relocate, reason, "years in Python", "current
  location", an unknown).
- `resolve_answer` personal + stored value → `source="profile"`, exact text.
- `resolve_answer` personal + unset → blank, `needs_user`, `no_stored_value`,
  and **LLM never called** (assert via a spy `llm`).
- `resolve_answer` groundable → uses a fake `llm` returning a grounded answer →
  `source="resume"`.
- `resolve_answer` groundable + grounding fail (fake `llm` invents a company
  fact) → blank, `grounding_failed`.
- `resolve_answer` unknown question → blank, `unknown_question`.
- No-fabrication: a CTC question with unset field returns `""` (never a number).

Résumé push (`tests/test_naukri_resume.py`, fake NopeRi client via
`client_factory` — no network, same pattern as `test_naukri_source.py`):

- Successful push + verify (fake reports the pushed basename live) → `ok=True`,
  `live_resume_name` set.
- Verify mismatch that never resolves → `ok=False`, `error="verify_timeout"`;
  **never raises**.
- `update_resume` returns non-2xx → `ok=False`, `error="upload_rejected"`.
- Missing/unreadable session → `ok=False`, `error="no_session"`; client factory
  never called.
- Client raises (blocked/token expired) → `ok=False`, `error=<ExcType>`.
- `verify=False` skips the read-back and returns `ok=True` on a 2xx push
  (escape hatch; runbook default is `verify=True`).

Store (`tests/test_apply_store.py`, extend):

- Round-trip `current_ctc` + `reason_for_change` through
  `save_/get_application_profile`.
- `ALTER TABLE` guard is idempotent on an already-migrated DB.

Browser step is manual per the runbook (parity with the other live e2e runs).

## Global constraints

- Python 3.11, stdlib `sqlite3`, `pytest`; files under 500 lines.
- Never fabricate; personal facts never sent to the LLM.
- Never auto-submit; candidate sends the final message.
- Naukri **source** stays read-only. NopeRi **résumé-write** (`update_resume`) is
  imported only in `apply/naukri_resume.py`; NopeRi **apply** code is never
  imported anywhere.
- Never apply on an unverified résumé — `push_resume` must return `ok=True` first.
- `apply/naukri_resume.py` and `apply/naukri_answers.py` never raise (parity with
  the read-only source and `draft_screening_answer`).
- Reuse existing seams: `draft_screening_answer`, `check_grounding`,
  `assemble_application_package`, `get_/save_application_profile`, and the
  source's session-restore pattern (`_default_client_factory`).
