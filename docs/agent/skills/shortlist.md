---
description: Build a shortlist of jobs to apply to on given boards, post it to the Inbox, and queue it
---
# Shortlist jobs to apply to

1. **Read the brief:** `get_about_me` for the target role, location and constraints, and `get_profile` for where the user can work.
2. **Search each board:** `search_jobs` with `source` set to that board (linkedin, wellfound, himalayas) and the role's synonyms.
3. **Read candidates:** read the strongest ones with `get_job`.
4. **Drop jobs that don't fit:**
   - jobs the user can't take: a location they can't work in ("US only", say), the wrong level, a broken constraint;
   - jobs already applied to;
   - closed or stale postings.
5. **Rank:** order by fit. Take the number asked for per board plus a few spares, because some will be skipped at a captcha or a sign-in.
6. **Post the shortlist:** `notify_user` with a table (job id, role, company, board, one-line reason), so the user
   can strike any. Don't wait for them unless they asked to approve first.
7. **Queue it:** `propose_action` with `POST /api/queue/batch`, `{"job_ids": [...], "start": true}`.
