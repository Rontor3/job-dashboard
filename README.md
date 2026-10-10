# Job Dashboard

A **local-first job-search dashboard**. It scrapes jobs from multiple boards, ranks them against *your* profile with a local LLM + embeddings, lets you **tailor a résumé** per role (LaTeX PDF), and **assists applications** (autofill, screening answers, cover letters) — all on your machine, with no paid API.

> Everything runs locally: the LLM is **Ollama** on your box, the embedder is a local sentence-transformer, and job data + your profile stay in a local SQLite DB and gitignored files. The only outbound traffic is scraping the job boards.

---

## What it does

- **Ingest** — pulls roles from Indeed & LinkedIn (via `jobspy`), Naukri (vendored fetcher), and Himalayas / RemoteOK / Remotive / WeWorkRemotely (their JSON APIs). Dedupes near-duplicates.
- **Rank** — classifies each job (industry / company-type), computes an embedding-similarity score against your profile, then an **LLM fit score + verdict**.
- **Résumé studio** — a block editor for your résumé (Experience / Projects / Skills). Generate bullets from rough notes, rewrite toward a JD, highlight keywords, suggest per-group skills — then render a **10pt LaTeX PDF**. Save named versions.
- **Apply assist** — a Chrome extension that autofills application forms from your profile; screening-question drafts; cover-letter generation; apply-type badges (⚡ ATS · ◐ LinkedIn/Indeed · ○ manual).
- **Track** — a Kanban tracker (saved → applied → interviewing → offer), plus a hiring-signals view.

---

## Prerequisites

| Tool | Why | Notes |
|------|-----|-------|
| **[uv](https://docs.astral.sh/uv/)** | manages ./.venv and Python 3.12 (`.python-version`) | `scripts/setup.sh` needs it |
| **Python 3.11** | backend (FastAPI) + pipeline | 3.10+ should work; 3.11 tested |
| **Node 18+ / npm** | frontend (React + Vite) | only to build the UI once |
| **[Ollama](https://ollama.com)** + a model | all LLM features (bullets, rewrite, ranking, screening) | default model `qwen3:14b` (set via `OLLAMA_MODEL` in `.envrc`) |
| **MacTeX / TeX Live** (`lualatex`) | render résumé PDFs | optional — everything else works without it |
| **Google Chrome** | LinkedIn/Naukri scraping (Selenium) + the autofill extension | optional per source |

Everything is CPU-friendly; a 14B model wants ~16 GB RAM (or swap in a smaller Ollama model — see below).

---

## Quick start

```bash
# 1. clone
git clone https://github.com/Rontor3/job-dashboard.git
cd job-dashboard

# 2. one-shot setup: python deps (./.venv via uv), Playwright Chromium
#    (project-local ./.playwright-browsers), frontend install + build,
#    Ollama (brew cask on macOS) + the qwen3:14b model (~9 GB download)
./scripts/setup.sh

# 4. local LLM — already done by setup.sh; to use another model see "Swap the model" below.
#    Load the model choice from .envrc (OLLAMA_MODEL=qwen3:14b), or export it yourself:
direnv allow

# 5. (optional) résumé PDFs — install MacTeX (macOS) or TeX Live (Linux)
#    macOS:  brew install --cask mactex-no-gui
#    Linux:  sudo apt-get install texlive-luatex texlive-latex-extra

# 6. run it
PYTHONPATH=src uv run python -m uvicorn job_dashboard.api.serve:app --port 8000
#    open http://localhost:8000  →  click "Refresh" to pull jobs
```

The SQLite DB (`data/jobs.db`) is created automatically on first run.

---

## Personalize it (the part that makes it *yours*)

This repo ships **placeholder** profile/résumé files. Your real details live in **gitignored `.local` overrides** the app prefers automatically — so nothing personal ever gets committed.

1. **Your profile** (used to LLM-rank jobs and ground résumé text):
   ```bash
   cp .claude/skills/ai-job-search/skills/job-application-assistant/01-candidate-profile.md \
      .claude/skills/ai-job-search/skills/job-application-assistant/01-candidate-profile.local.md
   # then edit the .local.md with your real experience, skills, goals
   ```

2. **Your résumé blocks** — edit the LaTeX segments in `src/job_dashboard/resume_segments/`:
   - Contact header & education carry personal info, so use `.local` overrides:
     ```bash
     cd src/job_dashboard/resume_segments
     cp header-contact.tex   header-contact.local.tex     # add your name/email/links
     cp education-btech.tex  education-btech.local.tex     # add your schools
     ```
   - Experience/Projects/Skills segments (`experience-*.tex`, `project-*.tex`, `skills-*.tex`) are edited in place, or from the **Résumés** tab in the UI. `segments.yaml` is the manifest.

3. **Application profile** (name/email/phone the autofill types) — set it once from the **Apply** panel in the UI, or `PUT /api/application-profile`.

4. **Scraper cookies** (only if you want LinkedIn/Naukri sources) — copy `.env.example` to `.env` and paste the session cookies it asks for. `.env` is gitignored.

---

## Swap the model

Every model call goes through one OpenAI-compatible **Responses API** client (`src/job_dashboard/llm.py`). The default is local Ollama (`http://localhost:11434/v1`, `qwen3:14b`). To swap, set these in `.env` (see `.env.example`):

```bash
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-5-mini
```

For local Ollama, raise the context length (Ollama app → Settings, or `OLLAMA_CONTEXT_LENGTH=16384`): hiring-post judging sends a résumé-sized prompt.

## Data and browser isolation

Everything the app writes (SQLite, run logs, résumés, credentials, the agent's browser profile, scratch files) lives under `data/` (or `$JOB_DASHBOARD_DATA_DIR`). Back up or move that one folder. The agent drives its **own** Chrome (separate profile at `data/browser/profile`, debug port 9333), launched on demand next to your everyday Chrome, which it never touches. Log in to job sites once in that window.

Smaller models are faster but less reliable at the résumé-writing rules; the code grounds every number/skill against your own text regardless, so it never fabricates.

---

## Tests

```bash
PYTHONPATH=src uv run python -m pytest -q      # backend
npm --prefix frontend run test           # frontend
```

---

## Honest limitations

- **Job boards bot-wall automation.** Indeed / LinkedIn / Naukri actively block scripted requests, so *ingestion* uses specialized fetchers (jobspy, a logged-in Selenium session, source APIs) — and **liveness/"is this still open?" checks can only reliably verify the sources that don't bot-wall**. Stale postings are pruned by age as a fallback.
- **The autofill never submits.** It fills fields and stops; you review, attach your résumé, and submit. It won't touch passwords, OTPs, or consent boxes.
- **Local-LLM variance.** A 14B model varies run-to-run; regenerate if a bullet reads awkwardly. All numbers/skills are grounded to your input, so output is truthful even when phrasing wobbles.
- **Work authorization is yours to set** — the ranker doesn't infer visa eligibility; set it in your application profile so region-mismatched roles can be flagged.

---

## Layout

```
src/job_dashboard/
  api/            FastAPI routes (jobs, resume, apply, letters, hiring)
  sources/        job-board fetchers (jobspy, himalayas, remoteok, naukri, …)
  match/          embeddings, LLM ranking, liveness sweep, eligibility
  resume/         segment engine, LaTeX render, bullet/skill LLM helpers
  resume_segments/  your résumé content as LaTeX blocks (+ .local overrides)
  apply/          application profile, screening answers, ATS field maps
frontend/         React + Vite UI (built to frontend/dist, served by the API)
extension/        Chrome autofill extension (load unpacked)
tests/            pytest suite
```

---

## License

No license file yet — add one (MIT is a common choice) if you want others to reuse it.
