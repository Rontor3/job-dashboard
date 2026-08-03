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
2. **Apply (browser, visible):** the agent answers Naukri's chatbot screening
   questions from a **reusable Answer Bank** (grounded answers precomputed from
   the profile + résumé, matched by meaning so paraphrases reuse the same
   answer), interrupting the candidate only for **new/exceptional** questions.
   Because the chatbot **commits each answer on Enter**, every answer is
   **reviewed before it is typed**, and the candidate sends the final message.

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
2. `apply/naukri_answers.py` — the **Answer Bank + resolver**: precompute grounded
   answers per intent once, match each chatbot question by meaning (keyword +
   embedding via the existing all-MiniLM-L6-v2 model), reuse known answers, pause
   only for exceptional ones. Pure logic, no browser, never raises.
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

Naukri asks the *same* handful of questions in many phrasings ("years of
experience", "how many years in AI", "proficiency in Python", "how long have you
worked with Python"). So the resolver is built around a **reusable Answer Bank**:
grounded answers precomputed once per candidate, keyed by *intent*, matched to
each incoming question by meaning (not exact words), and **reused across every
job and phrasing**. The candidate is only interrupted for a genuinely **new /
exceptional** question.

```python
@dataclass
class AnswerResult:
    text: str            # "" when needs_user
    source: str          # "bank" | "profile" | "unanswered"
    needs_user: bool     # True => candidate must supply/confirm (exceptional)
    flag: str | None     # "exceptional" | "skill_not_on_resume" | "no_stored_value"

@dataclass
class BankEntry:
    intent: str          # e.g. "total_experience", "skill:python", "notice_period"
    phrasing: str        # canonical question text, embedded for matching
    text: str            # the grounded answer
    source: str          # "bank" (résumé-derived) | "profile" (stored field)

def build_answer_bank(package, llm=None, embedder=None) -> list[BankEntry]
def resolve_answer(question: str, bank, package, embedder=None) -> AnswerResult
```

### `build_answer_bank` — precompute once, reuse everywhere

Built from the candidate's résumé + stored profile (rebuilt when either changes,
keyed by the profile hash the embedder already computes). Entries:

- `total_experience` — from `years_experience` / résumé.
- `skill:<s>` for **each skill on the résumé** (python, sql, ml, nlp, …) —
  answer drafted via `draft_screening_answer(research=None)` and passed through
  `check_grounding`; a résumé-grounded "N years / proficiency" line.
- Personal fields from the stored profile: `notice_period`, `current_ctc`,
  `expected_ctc` (`salary_expectation`), `willing_to_relocate`,
  `reason_for_change`, `location`. Only fields that are **set** become entries.

Each entry's `phrasing` is embedded (all-MiniLM-L6-v2 — the model already used
for job ranking; no new dependency) so paraphrases match.

### `resolve_answer` — match, reuse, or pause

1. **Extract a skill token** if the question names one ("python", "java", …).
   - Skill **on résumé** → return the `skill:<s>` bank entry (`source="bank"`).
   - Skill **not on résumé** → **pause**: `needs_user=True`,
     `flag="skill_not_on_resume"` (decision: never auto-answer a skill the
     candidate hasn't listed — they may want to speak to it themselves).
2. **Keyword rules** for the fixed intents (CTC/salary/"lpa", notice, relocate,
   reason, total experience, location) → the matching bank/profile entry; if the
   mapped profile field is **unset** → `needs_user=True`, `flag="no_stored_value"`.
3. **Semantic match** (paraphrase fallback): embed the question, take the
   nearest bank `phrasing` by cosine; **≥ threshold (0.60)** → reuse that entry.
4. **No confident match** → **exceptional**: `needs_user=True, flag="exceptional"`.

Reused entries fill **without interrupting** the candidate; only steps 1-(not on
résumé), 2-(unset), and 4 stop for them. Personal facts are **never** sent to the
LLM and never guessed. The résumé-derived entries carry no company specifics
(`research=None`), so `check_grounding` blanks anything unsupported. The resolver
**never raises**.

## Data flow (browser run, per runbook)

1. Candidate clicks **Apply (Naukri)** on a card → `assemble_application_package`
   (existing) builds `{profile, resume, cover_letter?, job}`.
2. **Push + verify (NopeRi, headless):** `push_resume(resume.pdf_path)` uploads
   the tailored PDF to the Naukri profile and read-back-verifies it is live.
   `ok=False` → **stop and report**; do not open Apply. Skipped only if the
   candidate has no tailored résumé for this job (falls back to whatever profile
   résumé is already live).
3. `build_answer_bank(package)` — once, before opening Apply (or reuse the cached
   bank if the profile/résumé is unchanged).
4. Agent opens the Naukri job in the candidate's **real Chrome** (logged-in
   session), clicks Apply; the chatbot appears, **one question at a time**.
5. **Per question — review BEFORE typing** (Naukri's chatbot **sends each answer
   on Enter**, so typing *is* submitting; confirmed live 2026-08-02):
   a. `resolve_answer(question, bank, package)`.
   b. **Reused/known answer** (`needs_user=False`) → show the candidate the
      drafted answer; on their **OK**, the agent types it. **Exceptional**
      (`needs_user=True`) → the candidate supplies/edits the answer themselves.
   c. Only after approval is the answer typed/sent — never type-then-review.
6. The **final** question's answer is **sent by the candidate**, not the agent.

**Hard rule (from the live incident):** on Naukri the agent must **draft →
candidate approves → then type**. It must never type into the chat box before the
candidate has approved that specific answer, because the box commits on Enter.

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
- LLM/embedder unavailable at bank-build → résumé-derived `skill:<s>` entries
  can't be drafted, so those questions resolve to `needs_user` (candidate
  answers); personal facts are unaffected (from the stored profile, never LLM'd).
  A missing expected bank entry always degrades to `needs_user`, never a guess.
- No stored personal answer → `needs_user`, `flag="no_stored_value"`; nothing
  invented.

## Testing

Unit (`tests/test_naukri_answers.py`) — a **fake embedder** (deterministic
vectors keyed by string) and fake `llm`, no model download:

- `build_answer_bank` produces one `skill:<s>` entry per résumé skill + entries
  for each **set** profile field, and **no** entry for unset fields.
- **Paraphrase reuse:** "years in Python", "proficiency in Python", "how long
  have you worked with Python" all resolve to the same `skill:python` bank entry
  (`source="bank"`, identical text) — the core requirement.
- **Skill not on résumé** ("proficiency in Java", Java absent) → `needs_user`,
  `flag="skill_not_on_resume"`; LLM not called for it.
- Personal + stored value ("notice period?") → `source="profile"`, exact text.
- Personal + unset (CTC unset) → `needs_user`, `no_stored_value`, and returns
  `""` (never a fabricated number); LLM never called (spy `llm`).
- **Exceptional** — a question matching no intent and below the 0.60 threshold →
  `needs_user`, `flag="exceptional"`.
- Semantic match above threshold reuses the nearest bank entry; below threshold
  does not (boundary test with the fake embedder).

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
- **On Naukri, typing into the chat box commits on Enter — so the agent must
  draft → candidate approves → then type, per question. Never type before
  approval.** (Reuse the embedding model already in the project — no new model.)
- Naukri **source** stays read-only. NopeRi **résumé-write** (`update_resume`) is
  imported only in `apply/naukri_resume.py`; NopeRi **apply** code is never
  imported anywhere.
- Never apply on an unverified résumé — `push_resume` must return `ok=True` first.
- `apply/naukri_resume.py` and `apply/naukri_answers.py` never raise (parity with
  the read-only source and `draft_screening_answer`).
- Reuse existing seams: `draft_screening_answer`, `check_grounding`,
  `assemble_application_package`, `get_/save_application_profile`, and the
  source's session-restore pattern (`_default_client_factory`).
