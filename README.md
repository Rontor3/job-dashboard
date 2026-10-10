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
| **curl** | `./jobdash setup` fetches [mise](https://mise.jdx.dev) into `./.mise` | mise then installs the pinned Node, Python, uv, pnpm and process-compose (`mise.toml`) inside the repo |
| **An LLM endpoint** | all LLM features (bullets, rewrite, ranking, screening) | any OpenAI-compatible Responses API; local [Ollama](https://ollama.com) works (`qwen3:14b`) |
| **MacTeX / TeX Live** (`lualatex`) | render résumé PDFs | optional — everything else works without it |
| **Google Chrome** | LinkedIn/Naukri scraping (Selenium) + the autofill extension | optional per source |

Everything is CPU-friendly; a 14B model wants ~16 GB RAM (or swap in a smaller Ollama model — see below).

---

## Quick start

```bash
# 1. clone
git clone https://github.com/Rontor3/job-dashboard.git
cd job-dashboard

# 2. one-shot setup, all inside the repo: the toolchain (./.mise), python deps (./.venv via uv),
#    Playwright Chromium (./.playwright-browsers), frontend install (pnpm) + build
./jobdash setup

# 4. LLM — set LLM_BASE_URL / LLM_MODEL in .env (copied into the config table on first start).
#    For local Ollama: install it, `ollama pull qwen3:14b`, and enable the `ollama` process in ./jobdash start.

# 5. (optional) résumé PDFs — install MacTeX (macOS) or TeX Live (Linux)
#    macOS:  brew install --cask mactex-no-gui
#    Linux:  sudo apt-get install texlive-luatex texlive-latex-extra

# 6. run it
./jobdash start          # api, in-app agent, worker and the agent browser under process-compose; ./jobdash dev for hot reload
#    opens http://localhost:8000 as a tab in the agent's own Chrome window — agent runs open as tabs beside it
#    →  the setup banner / Agent tab walks you through the rest (model, profile, résumé) in the app
#    →  click "Refresh" to pull jobs
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

Every model call goes through one OpenAI-compatible **Responses API** client (`src/job_dashboard/llm.py`). The default is local Ollama (`http://localhost:11434/v1`, `qwen3:14b`). Non-secret settings live in the `config` table of `data/jobs.db` and are read on every call, so a change applies without a restart (`GET`/`PUT /api/config/{KEY}`). On first start the values in `.env` are copied there; the API key stays in `.env`. To swap:

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
./jobdash test           # backend (pytest) + frontend (vitest)
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
