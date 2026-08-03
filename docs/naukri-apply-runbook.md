# Naukri Chatbot Apply Runbook (browser procedure)

This is the procedure a candidate follows to apply to a Naukri job via the **Naukri
chatbot**, using this dashboard's resume push and answer bank to draft their
responses. Unlike the Application Agent (which fills external ATS forms), this
runbook is **Naukri-specific**: the candidate opens the job in their own browser,
the Naukri chatbot asks questions, and the candidate — armed with pre-drafted
answers — responds interactively.

The key constraint: **the chatbot commits each answer on Enter**. The candidate
must review every drafted answer *before* typing it, never blind-commit.

## Preconditions

- A **valid, cached Naukri session** exists at `data/naukri_session.json` (run
  `scripts/naukri_login.py` to set it up). This session is used only for
  resumé push; the candidate's own Naukri browser session applies the job.
- The candidate is **logged into Naukri** in their real Chrome browser (not
  Claude-controlled).
- A **tailored resumé PDF** for this job exists in the dashboard. The candidate
  has reviewed and approved it (it's the current `resume_pdf_path` for the job
  in `resumes_for_job`).
- The candidate has filled their **application profile** in the dashboard (full
  name, email, phone, location, work authorization, etc.), and it's up-to-date.

## Procedure

### Step 1: Preconditions Check (before opening Naukri)

Confirm:

- `data/naukri_session.json` exists and is recent (created within the last few
  days; if older, re-run `scripts/naukri_login.py`).
- The candidate is logged into Naukri in their browser (visit `naukri.com` to
  verify).
- The dashboard's application profile is complete (check the Profile tab).
- The resumé PDF for this job is ready (visible in the dashboard's job card).

### Step 2: Detect Apply vs. Apply on Company Site

1. Open the job URL in the candidate's Naukri browser.
2. Look at the **primary call-to-action button** near the job title / description.
   - **If it says "Apply on Company Site"**: this job uses an external ATS
     (Workday, Lever, Greenhouse, etc.). Close this runbook and follow
     `docs/application-agent-runbook.md` instead. Do NOT proceed.
   - **If it says "Apply"** (and opens a chatbot): continue to Step 3.

### Step 3: Push and Verify Résumé

The candidate's resumé reaches Naukri via a **direct upload** (not in-chat). This
must succeed before proceeding to the chatbot.

1. Run **`push_resume(pdf_path)`** in the dashboard (or via the CLI):
   - `pdf_path` is the path to the tailored resumé PDF for this job.
   - The function connects to the cached Naukri session and uploads the PDF.
2. **Hard stop:** check the return value `PushResult`:
   - If `ok=True`: resumé uploaded successfully. Continue to Step 4.
   - If `ok=False`: **STOP immediately**. Check `error`:
     - `no_session`: the session is invalid or expired. Re-run `scripts/naukri_login.py`.
     - `upload_rejected`: Naukri rejected the file (format, size, or corruption).
       Inspect the resumé, re-export it, and try again.
     - Other exception (e.g., `RuntimeError`, `ConnectionError`): network error or
       Naukri API change. Consult the error log.
   - Note: if `ok=True` but the filename cannot be confirmed in Naukri's response,
     `live_resume_name` is `None` — the upload succeeded regardless.
   - **Under no circumstance proceed to the chatbot if `ok=False`.** The job
     application will fail without a resumé.

### Step 4: Build the Answer Bank

Before the candidate enters the chatbot, pre-draft answers to common questions.

1. Call **`build_answer_bank(application_package, embedder=load_default_model())`** in the dashboard:
   - Import the embedder: `from job_dashboard.match.embedder import load_default_model`.
   - `application_package` is the result of `assemble_application_package(conn, job_id)`.
   - The function extracts skills from the candidate's profile text (via
     `compose_profile_text`) and uses the LLM through `draft_screening_answer(...)` to
     build a bank of `BankEntry` objects, each with:
     - `intent`: the question intent (e.g., `skill:python`, `current_ctc`, `total_experience`).
     - `text`: a pre-written answer.
     - `source`: whether the answer came from the profile (stored fields) or the bank (LLM-drafted).
   - **Important:** the `embedder` parameter MUST be passed, or semantic paraphrase-reuse
     will be silently OFF (entries won't have vectors, and cosine matching will fail in Step 5).
2. **Rebuild the bank** when the profile or resumé changes; otherwise, the
   existing bank can be reused.
3. Store the bank in memory (or a `.json` file in the temp directory) so the
   candidate can access it during the chatbot.

### Step 5: Apply — Review Before Typing

The candidate now enters the Naukri chatbot and responds to each question. This
is the critical step: **the chatbot commits every answer on Enter**, so the
candidate must approve each draft before it's sent.

1. **Click "Apply"** on the Naukri job page. The chatbot opens.
2. **For each question the chatbot asks:**
   1. **Resolve the answer** from the bank:
      - Call **`resolve_answer(question, bank, embedder=model)`** in the dashboard
        (use the same model loaded in Step 4).
      - This function first tries keyword matching (for personal fields), then
        matches the question against the bank using cosine similarity on embeddings,
        and returns an `AnswerResult`:
        - `needs_user=False`: a draft answer was found in the bank. Show it to
          the candidate.
        - `needs_user=True`: the question is novel, or asks about a skill not on
          the resumé, or is an UNSET personal field (`current_ctc`,
          `reason_for_change`, etc. with no stored value). The candidate must
          type it themselves. (SET personal fields auto-answer.)
   2. **If `needs_user=False`:**
      - Show the draft answer to the candidate. (Print it to the console or
        display it in the dashboard's Apply modal.)
      - Ask: *"Is this OK? (Y/N)"*
      - On **Y**: the candidate reviews it and agrees. **Type the answer into
        the chatbox and press Enter.** The chatbot advances.
      - On **N**: the candidate edits or skips. They can modify the draft or
        type a completely new answer, then press Enter themselves.
   3. **If `needs_user=True`:**
      - Tell the candidate: *"This question is not in the pre-drafted bank. Type
        your own answer below."*
      - The candidate types their answer into the chatbox and presses Enter.
      - The chatbot advances.
3. **Repeat for all questions** until the chatbot presents the final "Send
   application" or "Confirm and send" message.

**Critical rule: Never type an answer before the candidate approves it.** The
chatbot's Enter key is a commit point — once sent, the answer cannot be edited.

### Step 6: Candidate Sends the Final Message

The candidate has filled all chatbot questions. The chatbot now shows a final
"Confirm and send" or "Submit application" message.

1. The candidate **reviews the full application one last time** on the chatbot's
   summary screen.
2. The candidate **clicks the final send button** *themselves*. (The agent never
   sends the final answer.)
3. Naukri confirms: *"Application submitted."*

### Step 7: No In-Chat Resumé Upload

Naukri may show a resumé-upload control *inside* the chatbot (in-chat, after
certain questions). **Ignore it.** The resumé was already uploaded in Step 3.

**Rare exception:** If Naukri shows a *mandatory* upload control and rejects the
submission without it, use the in-chat uploader *once* (upload the same PDF). Then
submit. But this should not happen if Step 3 succeeded.

### Step 8: Record the Application

On successful submission, record the application in the dashboard so it's marked
as applied.

1. Call **`save_application(conn, job_id, ...)`** with:
   - `resume_id`: the ID of the resumé uploaded in Step 3.
   - `screening`: a list of the questions and answers the candidate submitted
     (e.g., `[{question: "...", answer: "..."}, ...]`).
   - `ats="naukri"`: hard-coded for this job source.
   - `status="applied"`: the job is now applied.
2. The dashboard updates the job card: ✓ Applied.

## Notes and Warnings

### Personal Facts Are Never Fuzzy-Matched

The semantic similarity fallback (`resolve_answer`'s embedding-based matching)
only reuses **skill answers** (derived from the candidate's profile text via
`compose_profile_text`). Personal questions (CTC, notice period, location, etc.)
that don't match the keyword rules will **always pause** and require the candidate
to type them — they are never auto-filled via a loose cosine hit. This prevents
wrong personal values from sneaking in.

### Session Expiry

If the Naukri session expires mid-apply (rare), the candidate will see a login
wall. **Stop, tell them to log in**, and start over from Step 1. Re-run
`scripts/naukri_login.py` if the session file is older than a few days.

### Pausing for Review

The candidate should pause and review each drafted answer *in the chatbox* before
pressing Enter. This is the only moment to catch errors. Once Enter is pressed,
Naukri submits the answer and moves to the next question.

### Answer Bank Updates

If the candidate believes a draft answer is wrong or incomplete, they can:
- Edit it before sending (do not send the draft; type a new version).
- Accept it now and note the job URL for later review (if eligibility or
  feedback flags it as weak).

### Browser Session

The candidate uses their own Naukri browser session. Claude does not control the
chatbot — the candidate interacts directly. Claude's role is to pre-draft answers
and guide the candidate through the process.

### Conflict with Naukri UI

Naukri's UI may change (new question types, different button labels). If the
chatbot's flow diverges from this runbook (e.g., it asks for an upload before
Step 3, or skips some questions), **stop and consult the job's JD and Naukri's
help**. The procedure assumes Naukri's standard flow.
