# Job Evaluation Framework

<!-- SETUP: Skill match areas and career goals are personalized by running /setup -->

## Scoring Dimensions

Evaluate each job posting against these five dimensions:

### 1. Technical Skills Match (0-100)
How well do the required/preferred skills align with the candidate's capabilities?

| Score | Meaning |
|-------|---------|
| 80-100 | Core requirements are primary skills |
| 60-79 | Most requirements match, 1-2 gaps that are learnable |
| 40-59 | Partial match, significant upskilling needed |
| 0-39 | Fundamental mismatch |

**Strong match areas:** Python; ML/DL & NLP; GenAI/LLM engineering (RAG, LoRA fine-tuning, sentence-transformers embeddings, prompt engineering); fraud/anomaly detection; model explainability (SHAP); AWS Lambda/API Gateway/DynamoDB; real-time model serving / production ML
**Moderate match areas:** SQL; broader MLOps (orchestration, CI/CD for ML); AWS SageMaker; LangChain / agentic patterns; quantitative/financial modeling (Monte Carlo, backtesting); Streamlit
**Weak match areas:** large-scale distributed training; deep infra (Kubernetes, heavy DevOps); non-Python stacks; formal research publications; front-end/UI engineering

### 2. Experience Match (0-100)
Does work history align with what they're looking for?

| Score | Meaning |
|-------|---------|
| 80-100 | Direct experience in the same domain and role type |
| 60-79 | Related experience, transferable skills clear |
| 40-59 | Adjacent experience, would need to make the case |
| 0-39 | Unrelated experience |

**Strong:** production fraud/anomaly ML in insurance (health); applied LLM/GenAI project work (RAG, LoRA fine-tuning); real-time model serving on AWS
**Moderate:** quantitative/financial modeling; marketing/engagement analytics; MLOps at larger org scale
**Entry-level:** pure-research positions; big-tech-scale distributed systems; formal team leadership/management

### 3. Behavioral/Culture Fit (0-100)
Does the role and company culture match the behavioral profile?

| Score | Meaning |
|-------|---------|
| 80-100 | Culture strongly matches behavioral preferences |
| 60-79 | Mixed signals but mostly compatible |
| 40-59 | Some friction areas |
| 0-39 | Significant culture mismatch |

**Red flags to research:** Department disorganization, work dominated by maintenance over development, poor chemistry with leadership, culture mismatches. Check reviews, media coverage, LinkedIn connections, and network contacts for insider perspective.

### 4. Location & Logistics (visa-aware, region-specific ranking)
Candidate is **India-based**. A US work visa (H1B) is **not** realistically available —
this changes the rules per region (user directive 2026-07-17):
- **Remote (Worldwide / India-eligible): PASS — ideal.** Verify the posting doesn't
  restrict remote hiring to US-only ("US work authorization required" = treat as US onsite).
- **US-based roles: REMOTE ONLY.** Onsite or hybrid in the US = **deal-breaker**
  (add flag "requires US work authorization") → Poor Fit regardless of technical match,
  unless the posting explicitly allows working remotely from India or explicitly offers
  visa sponsorship + relocation (then FLAG for discussion instead).
- **Europe-based roles: remote preferred.** Onsite/hybrid Europe = strong DOWN-RANK
  unless explicit visa sponsorship is stated (easier than H1B, still a barrier — FLAG).
- **India roles: remote, hybrid, AND onsite all PASS** — no penalty for any work mode.
- Frequent international travel: FLAG (discuss with user)

### 5. Career Alignment & Motivation (0-100)
Does this role advance career goals and contain tasks that energize?

| Score | Meaning |
|-------|---------|
| 80-100 | Strongly aligned with career direction, clear growth path |
| 60-79 | Good role but only partially aligned with long-term goals |
| 40-59 | Decent job but doesn't build toward career goals |
| 0-39 | Dead end or backwards step |

**Career goals:**
- Move into AI Engineer / ML Engineer / Senior Data Scientist / DS3 (or related new titles) — kept broad on purpose, not narrowed to one track.
- Deepen GenAI/LLM engineering (RAG, fine-tuning, agents, applied LLM) while retaining production/MLOps ownership.
- Remote-first roles; open to India and abroad; open to contract/freelance alongside full-time.

**Motivation filter:** Evaluate not just whether you *can* do the tasks, but whether the tasks will *energize* you. Consider:
- Tasks that energize: building/shipping ML & LLM systems end-to-end; GenAI experimentation (RAG, fine-tuning, agents); owning models in production
- Tasks that drain: pure BI/dashboarding/reporting; manual analysis with no modeling; roles with no modern ML/LLM component
- Non-task factors: leadership style, department culture, company values, degree of autonomy

**Life situation alignment:** Consider personal constraints:
- **Security**: currently employed (Tata AIG) — can be selective; not a forced/urgent move
- **Flexibility**: remote-first strongly preferred
- **Professional development**: prioritizes modern GenAI/LLM depth and increased scope

### 6. Salary Benchmark (Optional)

If the salary lookup tool is configured (`salary_data.json` exists), look up the company:
```
python .claude/skills/ai-job-search/salary_lookup.py "<Company Name>" --json
```

If a city is known from the posting, add `--city "<City>"` to narrow results.

Present findings as:
```
### Salary Benchmark
| Metric | Value |
|--------|-------|
| [Category] index | XX.X (+/-X.X% vs baseline) |
| Overall index | XX.X (+/-X.X% vs baseline) |
```

Interpret results relative to the baseline defined in the data file's metadata. For index-based data, higher typically means above-market compensation.

If the salary tool is not configured, skip this section.

## Output Format

Present the evaluation as:

```
## Job Fit Evaluation: [Role] at [Company]

| Dimension | Score | Notes |
|-----------|-------|-------|
| Technical Skills | XX/100 | [brief note] |
| Experience Match | XX/100 | [brief note] |
| Behavioral Fit | XX/100 | [brief note] |
| Location | PASS/FAIL | [brief note] |
| Career Alignment | XX/100 | [brief note] |

**Overall Score: XX/100** (weighted average of scored dimensions)

### Verdict: [Strong Fit / Good Fit / Moderate Fit / Weak Fit / Poor Fit]

### Key Strengths for This Role
- [bullet points]

### Gaps to Address
- [bullet points]

### Recommendation
[1-2 sentences: apply/skip/apply with caveats]

### Company Research Checklist
- [ ] Checked company website (mission, values, recent news)
- [ ] Checked review sites (Glassdoor, Jobindex, etc.)
- [ ] Checked LinkedIn for team size, recent hires, connections
- [ ] Checked media for restructuring, growth, or workplace issues
- [ ] Identified network contacts who may know the team/manager
```

## Weighting
- Technical Skills: 30%
- Experience Match: 25%
- Behavioral Fit: 15%
- Career Alignment: 30%

(Location is pass/fail, not weighted)

## Thresholds
- **Strong Fit** (75+): Definitely apply, tailor everything
- **Good Fit** (60-74): Apply, address gaps in cover letter
- **Moderate Fit** (45-59): Consider carefully, discuss with user
- **Weak Fit** (30-44): Probably skip unless strategic reasons
- **Poor Fit** (<30): Skip

## Pre-Application: Call the Employer (Best Practice)

Before writing the application, consider whether the candidate should call the contact person listed in the posting. **Only call if there are substantive questions** - never call just to "be remembered."

### When to Suggest Calling
- The posting has unclear or ambiguous requirements
- It's unclear which competencies are essential vs. nice-to-have
- The role description is vague about day-to-day tasks
- There's a named contact person who invites questions

### Good Questions to Ask
- "What are the primary challenges in this role?"
- "How is time typically divided across the listed responsibilities?"
- "Which competencies are most critical for success in this position?"
- "What does success look like in the first 6-12 months?"

### Rules for the Call
- Prepare a 30-second "elevator pitch" about your background in case they ask
- The call's purpose is **gathering information**, not delivering a pitch
- Take notes - use what you learn to tailor the application
- Reference the conversation naturally in the cover letter ("After speaking with [name], I was especially drawn to...")
