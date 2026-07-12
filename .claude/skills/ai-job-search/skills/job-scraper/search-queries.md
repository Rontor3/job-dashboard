# Search Queries for Job Scraper

<!-- Populated by /setup on 2026-07-13. Profile: Rakshit Singh. -->
<!-- Orientation: REMOTE-FIRST (global). Broad across target titles — deliberately
     not overfit to one narrow role. GenAI/LLM involvement, no-pure-BI, and
     remote-friendly are ranking preferences, not hard filters. -->

## Search Sites

Remote-first — the Job Aggregation backend (`src/job_dashboard/`) already covers
Remotive, RemoteOK, We Work Remotely, Himalayas, plus JobSpy (LinkedIn/Indeed/
Naukri/Glassdoor/Google Jobs/ZipRecruiter). These queries feed the JobSpy /
Google `site:` search layer.
- **linkedin.com/jobs** - filter: Remote (Worldwide), India
- **Remotive / RemoteOK / We Work Remotely / Himalayas** - remote-native boards (via backend)
- **naukri.com** - India coverage for India-based remote/hybrid
- Company career pages via Google `site:` searches for target companies

## Query Categories

Combine with `remote` and, secondarily, `India`. Titles are kept broad on purpose.

### Priority 1: Core target titles (AI / ML Engineer)

```
site:linkedin.com/jobs "AI Engineer" remote
site:linkedin.com/jobs "Machine Learning Engineer" remote
site:linkedin.com/jobs ("LLM Engineer" OR "GenAI Engineer") remote
"AI Engineer" OR "ML Engineer" remote (LLM OR RAG OR "fine-tuning")
```

### Priority 2: Senior Data Scientist / DS3 and domain strengths

```
site:linkedin.com/jobs "Senior Data Scientist" remote (LLM OR "machine learning")
site:linkedin.com/jobs "Data Scientist" remote (fraud OR "risk" OR anomaly)
"Data Scientist III" OR "DS3" remote
Data Scientist remote (MLOps OR "production ML" OR AWS)
```

### Priority 3: Adjacent GenAI / applied-LLM roles

```
site:linkedin.com/jobs ("Applied Scientist" OR "Applied AI") remote
"NLP Engineer" OR "Generative AI" remote
"MLOps Engineer" remote (Python OR AWS)
"AI/ML" (RAG OR LangChain OR "sentence-transformers" OR LoRA) remote
```

### Priority 4: Broader technical / contract net

```
"Machine Learning" OR "Data Science" contract remote
Python "machine learning" remote (startup OR "Series A" OR "Series B")
freelance ("LLM" OR "GenAI" OR "machine learning") remote
```

## Location Filter

Remote-first — rank by remote availability, not commute:
- **Ideal:** Remote (Worldwide) or Remote (India) — no relocation required
- **Acceptable:** Remote within a compatible timezone band; India-based hybrid
- **Borderline:** On-site abroad WITH relocation/visa support
- **Too far / drop:** Strictly on-site-only with no remote option (unless exceptional fit)

## Ranking preferences (soft, not hard filters)

- **Prefer** roles involving GenAI/LLM work (RAG, fine-tuning, agents, applied LLM).
- **Down-rank** pure BI/dashboarding/reporting roles mislabeled as Data Science.
- **Require-ish** remote-friendliness (strong down-rank for on-site-only).
- Keep the net WIDE across titles — judge on overall fit, not title/keyword alone.

## Date Filter

Only include jobs posted within the last 14 days, or with a future application
deadline. If a posting date can't be determined, include it but flag "date unknown".

## Adapting Queries

If the user specifies a focus area, select the matching category and generate 2-3
custom focus-specific queries.
