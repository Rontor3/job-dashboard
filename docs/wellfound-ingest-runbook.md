# Wellfound Ingest Runbook (browser-session source)

Wellfound has **no public jobs API** and gates its GraphQL feed behind **login +
bot protection**, so it can't run in the unattended background refresh. Instead
it's an **on-demand, browser-session import**: read the candidate's own
logged-in feed, normalize it with `sources/wellfound_source.py`, and push it
through the existing pipeline. This is the procedure the assistant follows with
the Claude-in-Chrome tools.

## Preconditions

- The Claude-in-Chrome extension is connected (`mcp__claude-in-chrome__*`).
- The candidate is **logged into Wellfound** in that Chrome profile.
- The candidate's job search is set (role / location / filters). Recommended:
  tick **"Hide jobs which require me to apply on the company's website"** so only
  Wellfound-native quick-apply jobs are ingested.

## Procedure

1. **Open the feed** in a Claude-controlled tab: `navigate` to
   `https://wellfound.com/jobs` (their saved search applies). The tab may open in
   a background Chrome window — foreground it if the user wants to watch.
2. **Read the jobs.** Preferred: `read_network_requests` on the tab with
   `urlPattern: "graphql"` — Wellfound loads the feed via a POST to
   `wellfound.com/graphql`; its JSON response holds each listing (title, company,
   locationNames, remote, compensation, keywords/skills, `yearsExperienceMin`,
   `hiresRemotelyIn`/region, and the job **slug**/id). Fallback: `read_page` /
   `get_page_text` and parse the visible job cards. Scroll to load more as needed.
3. **Map to the raw-dict shape** `wellfound_jobs_from_raw` expects, per job:
   `{slug, title, company, location, remote (bool), salary, skills (list),
   years_experience, hires_remotely_in, description}`. Use the JD text for
   `description`; the normalizer appends the years + region so eligibility can
   parse them.
4. **Normalize + ingest.** Call `wellfound_jobs_from_raw(raw)` → `list[JobListing]`
   and POST them through the existing **ingest** path (the same one the other
   sources feed), so they run through **dedup → embeddings**.
5. **Rank.** Run the `/rank` deep-rank. The `record` path now applies eligibility:
   a job whose JD requires far more years than the candidate has, or that doesn't
   accept the candidate's region, is **capped to "Weak Fit"** with a flag — so it
   sinks below the Strong/Good jobs the dashboard shows by default.

## Notes

- **Read-only.** This never applies to a job — that's the separate Application
  Agent flow (`docs/application-agent-runbook.md`), always review-then-send.
- **Down-rank, not drop.** Ineligible jobs still land in the DB (as "Weak Fit");
  nothing is discarded, so the filtering is auditable.
- Some Wellfound listings redirect to an external ATS (Greenhouse/Lever/Workday);
  those are just normal jobs — the Application Agent handles them via those maps.
