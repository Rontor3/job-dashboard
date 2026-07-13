# /rank — Deep-rank top jobs against the profile

Score the highest-embedding-similarity unranked jobs with a full evaluation
against `.claude/skills/ai-job-search/skills/job-application-assistant/04-job-evaluation.md`.

## Steps

1. Fetch the batch (default 30; `$ARGUMENTS` may override with a number):

   ```bash
   python3 -m job_dashboard.rank_io top --db data/jobs.db --limit 30
   ```

   If the JSON array is empty, report "No unranked jobs — run the pipeline first" and stop.

2. Read `04-job-evaluation.md` once. For each job in the batch, dispatch a
   subagent (parallel, in groups of up to 5) whose prompt contains: the job's
   title/company/location/job_url/description JSON, the full text of the
   evaluation framework, and this output contract:

   > Evaluate this job against the framework's five dimensions and weighting.
   > Return ONLY a JSON object:
   > `{"llm_score": <int 0-100 weighted overall>, "verdict": "<Strong Fit|Good Fit|Moderate Fit|Weak Fit|Poor Fit>", "strengths": ["..."], "gaps": ["..."], "flags": {"deal_breakers": [], "deadline": null, "expired": false}}`

3. For each agent result, write it to a temp file and record it:

   ```bash
   python3 -m job_dashboard.rank_io record --db data/jobs.db --job-id <ID> --file <EVAL_JSON_PATH>
   ```

   A non-zero exit means the payload was invalid — retry that one agent once
   with the error message appended to its prompt; if it fails again, skip that
   job and continue (per-job isolation; one failure never aborts the batch).

4. Report a summary table: job title/company, llm_score, verdict — plus any
   skipped jobs and the count remaining unranked.
