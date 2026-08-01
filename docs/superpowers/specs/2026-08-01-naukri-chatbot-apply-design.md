# Naukri Chatbot Apply — Design

**Date:** 2026-08-01
**Status:** Approved (design), pending spec review
**Depends on:** Application Agent (`apply/` package), screening grounding guard

## Goal

Extend the existing browser Application Agent to handle Naukri's **conversational
chatbot apply**: the agent drafts grounded answers to Naukri's screening
questions from the candidate's tailored résumé + stored profile, presents the
full answer set for review, and **stops before the candidate sends the final
message**. Naukri ingest/search stays read-only and untouched.

## Non-goals

- No one-click instant-apply automation (agent stops the user *before* an
  irreversible instant-apply; it does not click it).
- No "Apply on company site" handling — those redirects already fall through to
  the existing ATS agent.
- No change to the read-only Naukri **source** (`sources/naukri_source.py`);
  apply/resume-upload code from the vendored NopeRi library is still never
  imported.
- No auto-submit, ever. The candidate sends the final chatbot message.

## Architecture

Naukri apply is a new **branch of the existing Application Agent**, not a new
subsystem. Three pieces:

1. `apply/naukri_answers.py` — the **resolver**: classify each chatbot question,
   route to profile / grounded-draft / blank. Pure logic, no browser, never raises.
2. `apply/store.py` — extend the single-row `application_profile` with the two
   missing Naukri personal-fact fields.
3. `docs/naukri-apply-runbook.md` — the **browser procedure** that drives the
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
2. Agent opens the Naukri job in the candidate's **real Chrome** (logged-in
   session), clicks Apply; the chatbot appears.
3. For each visible question: agent reads the text → `resolve_answer` → collects
   `AnswerResult`s.
4. Agent presents the **full list** — question → drafted answer → `source`, with
   `needs_user` items clearly flagged as blanks the candidate must fill.
5. Candidate approves/edits, then **sends the final message themselves**.
6. **Fallback:** if Naukri hides Q2 until Q1 is sent (draft-all impossible), the
   agent switches to **answer-then-pause per question** — fill one, wait for the
   candidate's go, never sending the last one automatically.
7. If the chatbot requests a file, the **tailored résumé** (`resume.pdf_path`) is
   uploaded.

## Error handling

- Not logged in / no Naukri session in Chrome → agent stops and tells the user.
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

Store (`tests/test_apply_store.py`, extend):

- Round-trip `current_ctc` + `reason_for_change` through
  `save_/get_application_profile`.
- `ALTER TABLE` guard is idempotent on an already-migrated DB.

Browser step is manual per the runbook (parity with the other live e2e runs).

## Global constraints

- Python 3.11, stdlib `sqlite3`, `pytest`; files under 500 lines.
- Never fabricate; personal facts never sent to the LLM.
- Never auto-submit; candidate sends the final message.
- Naukri source stays read-only; no NopeRi apply code imported.
- Reuse existing seams: `draft_screening_answer`, `check_grounding`,
  `assemble_application_package`, `get_/save_application_profile`.
