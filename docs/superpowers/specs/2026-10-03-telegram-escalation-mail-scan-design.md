# Telegram escalation + daily mail scan — design

Date: 2026-10-03 · Status: built · Slice 3 of the final functional flow.

## Telegram: ask live, park if unanswered

Decision: not a pure "park" — the agent asks on Telegram **in real time**, and only what is
still unanswered after a wait is parked on the tracker (the session-expiry case).

- Queue runs pass `--park --ask-wait-minutes N` (`agent_settings.telegram_wait_minutes`, default
  10, 0 = never ask; editable in the queue panel).
- `integrations/escalation.py::EscalationCollector` wraps the existing `TelegramCollector`:
  1. sends the **job description**, then the **company page** (`company_resources`), once per run;
  2. asks each unanswered question under **one shared deadline** (not N × wait);
  3. questions asked once are not re-asked; unanswered ones stay open → run ends `needs_human` →
     job parked as Failed "questions to answer" → one Telegram note; they wait on the tracker, and
     answering the last one re-queues the job.
- Approvals stay denied in queue mode: submitting is only ever auto-submit's job.
- Without Telegram configured, or with a wait of 0, `--park` behaves as before (ask nothing).

## Mail scan: follow the companies we applied to

Daily (and "Check email" button), read-only Gmail, local model only.

- Scans jobs in **Applied / Interviewing**. A mail matches a job when the company name (legal
  suffixes ignored) appears in the sender name, subject or sender domain, or it comes from a
  sender learned from that job's first company mail. Only matches are opened.
- Several jobs at one company: the one whose title the subject names, else the newest.
- Classified by the local LLM (acknowledgement / assessment / interview / offer / rejected /
  other, with the round if stated), keyword rules as fallback. Job-board mail
  (naukri, linkedin, …) counts only when decisive, and a board is never remembered as the company.
- Effects: interview → Interviewing (round = stated round, never lower than the current; first
  one = 1); offer → Selected; rejected → Rejected. Final states are never revived. Everything is
  stored in `job_mail` (one row per message id → re-scans are no-ops) and shown in the expanded
  tracker row.
- Daily loop is started by `api/serve.py` only (tests never scan).

## Not done

External-site applications do not yet capture their confirmation mail at submit time; the
sender is learned from the first matching company mail instead.
