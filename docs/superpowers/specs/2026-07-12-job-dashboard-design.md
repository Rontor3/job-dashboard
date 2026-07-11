# Job Dashboard — Design

## Purpose

An interactive dashboard that aggregates job (and contract/freelance) listings aligned to Rakshit's target roles, scores them against his real profile, helps him compose a tailored resume and cover letter per application, and supports cold outreach to company contacts — all from one place instead of manually working a dozen job boards.

## Who this is for

Rakshit is a Data Scientist (Tata AIG, since July 2023) targeting his next move as **AI Engineer, ML Engineer, Senior Data Scientist, DS3, or related new titles**. His resume undersells his current work — real strengths include modular fraud-detection ML pipelines in production (AWS Lambda/DynamoDB), an offline RAG system (Ollama + sentence-transformers), LoRA fine-tuning (Gemma) for LLM prompt recovery, and a prior project building an LLM-based resume/JD matcher with ATS scoring — which is directly relevant prior art for this dashboard's own matching engine. He's open to roles in India and abroad, remote included, and to contract/freelance work in addition to full-time.

## Subsystems and build order

The full vision decomposes into five subsystems, built in this order so each layer has something to sit on top of:

1. **Job aggregation** — pull listings from all sources into one normalized feed
2. **Dashboard UI** — browse/filter the feed, see match scores
3. **Resume engine** — ATS check + modular, tailored resume composition per application
4. **Cover letter generation** — grounded in real company research, not just the JD
5. **Outreach** — find company contacts, draft cold emails (send requires explicit per-message confirmation — see Outreach section)

Freelance marketplaces (Upwork, Toptal, Braintrust, Contra) and any UI/hosting/DB technology choices are explicitly deferred to the implementation plan — see Non-goals.

## 1. Job aggregation

### Sources and how each is pulled

| Source(s) | Method | Notes |
|---|---|---|
| Indeed, LinkedIn, Naukri, Glassdoor, Google Jobs, ZipRecruiter, Bayt, BDJobs | **[JobSpy](https://github.com/speedyapply/JobSpy)** (`pip install python-jobspy`, MIT, 3.7k★, actively maintained) | Returns full JD text, `job_type`, `emails`, salary, remote flag — no custom scraper needed |
| We Work Remotely, Remotive, RemoteOK, Himalayas | Direct RSS/JSON API calls | These boards expose public feeds; no scraping tool needed |
| Wellfound, jobs24x, unlistedjobs, remotejobs.io | **[Scrapling](https://github.com/d4vinci/Scrapling)** (69.1k★, BSD-3, Cloudflare/anti-bot bypass, stealth fetch) | Free alternative to paid services (Bright Data/Apify) for sites with bot protection and no API |
| Recently-funded startups (Google Sheet) | Periodic read of the sheet's public CSV/htmlview export | Sheet is live and manually updated — re-read on a schedule, don't scrape once and forget |
| Research fellowships/residencies (Anthropic Fellows Program, OpenAI/Google/Meta AI residencies, etc.) | Small curated static list of known program pages, checked periodically | Not a scraping problem — low volume, high signal |
| "Last 24h fresh hiring" social signal (HR/founder posts on LinkedIn/Twitter announcing they're hiring) | **agent-reach** (Panniantong's CLI — reads Twitter/Reddit/LinkedIn/YouTube without per-platform API fees) | Different signal type than job boards: catches roles before/without a formal posting |

No repo in the job-scraping space clears 10k★ — the space tops out around JobSpy's 3.7k and Scrapling's 69k (a general scraping framework, not job-specific). JobFunnel (2.1k★) was considered and rejected — archived/unmaintained.

### Matching

- **Semantic matching on full JD text**, not keyword/title filtering. Keyword filtering was rejected because it misses roles with unconventional titles and lets through irrelevant ones that happen to share a word — and layering a keyword pre-filter in front of semantic re-ranking was rejected too, since it would just inherit the same blind spot before semantic scoring ever runs.
- Reuses/extends Rakshit's own prior project, **AI-Powered Resume – LLM-based Resume & JD Matcher** (semantic similarity via Sentence Transformers + ATS scoring, already built Aug 2024), rather than building a matcher from scratch.
- Full JD text is required as input (not just title/snippet), which is why every source above must yield full description text, not just a feed summary.

### Persistent companies/contacts directory

Startup-sheet companies (and any company we look up a contact for) get a durable record — not a transient re-fetched list:
- Fields: company name, funding info/stage, source, contact(s) found
- Once a contact is looked up via Hunter.io/Skrapp, it's **saved permanently against the company** — never re-spend a lookup credit on a company we've already resolved
- The list **accumulates** across refresh cycles (dedup by company, append new entries), functioning as a growing personal CRM
- This directory is the backbone the Outreach subsystem reads from later

### Filters (dashboard-facing, built on data already in the feed)

- **Company type:** startup vs big MNC
- **Geography:** India, abroad, remote — no portal restricted to India-only
- **Employment type:** Full-time / Contract / Freelance / Research Fellowship — surfaced from the `job_type` field JobSpy and other sources already return. Dedicated gig marketplaces (Upwork, Toptal, etc.) are explicitly deferred (see Non-goals) since they need a bid/proposal action flow rather than "apply."

## 2. Dashboard UI

An interactive, browsable surface — not a CLI. Shows the aggregated feed with match scores and the filters above. UI framework/tech stack is left to the implementation plan.

## 3. Resume engine

Reuses backend logic from **[ai-job-search](https://github.com/MadsLorentzen/ai-job-search)** (MadsLorentzen, 21k★, MIT, built specifically for Claude Code) rather than building from scratch — but only its "brain," since it has no UI at all (confirmed: 100% CLI/Claude Code skills, LaTeX/PDF output, no web dashboard whatsoever despite the TypeScript in its repo being job-portal CLI scrapers, not a frontend):

- **ATS compatibility check**: extracts the PDF's actual text layer (`pdftotext`) and verifies it the way a real ATS parser sees it (contact details as literal text, no garbled glyphs, sane reading order), scores keyword coverage against what parsers actually extract. This directly satisfies the "check if it's ATS-friendly" requirement — checking the real PDF rather than applying generic rules (which is what the HackerRank ATS tool and similar resources would otherwise be used for).
- **Modular resume composition**: present segment/option boxes (skills blocks, project blocks, experience framing) the user picks per application, rather than one static resume.
- **Rendering reuses ai-job-search's LaTeX CV pipeline directly**: once segments are chosen for an application, the selected content is composed into the same LaTeX template system ai-job-search uses to produce its CV, and compiled to a polished PDF (via the same TeX Live/MacTeX + optional `poppler` toolchain) — rather than building a new resume-rendering system from scratch. New resumes are generated this way, then immediately run through the ATS check above before being finalized for an application.
- Drafter-reviewer agent pattern from ai-job-search is the reusable architecture for this and cover-letter generation.

## 4. Cover letter generation

Also reuses ai-job-search's approach: a reviewer agent **researches the actual company** (not just the job posting text) before drafting — satisfying the "deep dive into company portfolio" requirement. Bonus feature carried over at no extra cost: ai-job-search's `/interview` command researches the company + interviewers for interview prep, which wasn't asked for but is directly useful.

## 5. Outreach

- Uses the persistent companies/contacts directory (see Job Aggregation) to find CEO/HR contacts.
- **Contact-finder tooling**: [Hunter.io](https://hunter.io) as primary (free tier includes real API access — 50 credits/month, no card required) and [Skrapp.io](https://skrapp.io) as secondary (LinkedIn-based, 50 credits/month free) — combined ~100 free lookups/month, sized for personal job-search volume, not sales-team scale.
  - Rejected for automated use: ContactOut, Lusha, RocketReach — each gates real API access behind custom/enterprise-priced tiers; their free tiers are browser-extension-only and can't be called from an automated skill.
- **Cold email flow**: draft the message in the UI, but **do not auto-send**. Sending email on the user's behalf requires his explicit confirmation on each individual message — the UX should be "draft → review → user hits send," not an auto-pilot outreach loop.

## Non-goals (deferred, not part of this design)

- Dedicated freelance/gig marketplaces (Upwork, Toptal, Braintrust, Contra) and their bid/proposal action flow — revisit after v1 if surface-level contract-role filtering from existing sources proves insufficient
- UI framework, hosting, and database technology choices — left to the implementation plan
- Refresh/scheduling cadence specifics for each source — left to the implementation plan
- Auto-sending cold emails without per-message user confirmation — explicitly out of scope, not just unbuilt
