# Resume LLM Engine (Ollama) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Checkbox steps. Dispatch prompts in caveman style (project memory).

**Goal:** Turn the Resume Engine's crude no-LLM default into real tailoring by injecting a local Ollama (`qwen2.5:14b`) model at the existing `llm` seam — producing truthful keyword-mapped rephrasings — and feed `suggest` the job's already-stored LLM gaps so gaps stop being junk. Local, free, private; integrity guard + human-approval gate unchanged.

**Architecture:** New `resume/resume_llm.py` provides `make_ollama_llm(post=None) -> LlmFn` — a callable `(segments, jd_text) -> list[LlmProposal]` that prompts qwen2.5:14b (`format=json`, injectable HTTP `post`) per uncovered JD keyword and parses to `LlmProposal`. `create_app`'s default `resume_engine` wires it; the `suggest` endpoint passes the job's stored deep-rank gaps as the salient JD keywords. Ollama unreachable → suggest still returns blocks+gaps, never 500.

**Tech Stack:** Python 3.11+, Ollama HTTP API (`localhost:11434`, model `qwen2.5:14b`), pytest (HTTP mocked; one live smoke skipped when Ollama down).

## Global Constraints

- The injected llm returns RAW proposals; the existing `keyword_map` integrity guard (whitelist vs source + KNOWN_TOOLS + natural-casing) re-validates EVERY proposal and the human approves each diff. The Ollama prompt forbids fabrication, but the guard is the authoritative code control — do NOT weaken it.
- `LlmProposal(block_id, jd_keyword, proposed_text, confidence)`; confidence ∈ {exact-synonym, equivalent, transferable}. `LlmFn = Callable[[list[Segment], str], list[LlmProposal]]`.
- Ollama host/model from env: `OLLAMA_HOST` (default `http://localhost:11434`), `OLLAMA_MODEL` (default `qwen2.5:14b`).
- No test performs a real Ollama/network call except one explicitly-skipped live smoke; the HTTP `post` is injected/mocked everywhere else.
- Any Ollama failure (down, timeout, bad JSON) degrades to `[]` proposals — `suggest`/`generate` never 500 on it.
- No API key, no external network — fully local.

---

### Task 1: `resume_llm.py` — Ollama adapter → LlmFn

**Files:** Create `src/job_dashboard/resume/resume_llm.py`; Test `tests/test_resume_llm.py`.

**Interfaces:** `make_ollama_llm(post=None, model=None, host=None) -> LlmFn`. `post(url, json_body) -> dict` defaults to a real `requests.post(...).json()`; tests inject a fake. The returned LlmFn: for each salient JD keyword not already in a block's text, pick the best-matching block (keyword/tag overlap), prompt qwen2.5:14b for a truthful rephrasing, parse `{proposed_text, confidence}` → `LlmProposal`. Skips/keeps None on any parse/HTTP error (never raises).

- [ ] Step 1 — failing tests (inject a fake `post`):

```python
# tests/test_resume_llm.py
from job_dashboard.resume.resume_llm import make_ollama_llm
from job_dashboard.resume.keyword_map import LlmProposal
from job_dashboard.resume.segments import Segment
from pathlib import Path


def _seg(id, text, tags):
    return Segment(id=id, kind="project", title=id, tags=tags,
                   tex_path=Path(id), text=text, exclusive_group=None)


def test_ollama_llm_maps_keyword_to_proposal():
    segs = [_seg("p-rag", r"\item Built offline RAG with Ollama + sentence-transformers embeddings", ["rag", "embeddings"])]
    calls = []

    def fake_post(url, json_body):
        calls.append(json_body)
        return {"response": '{"proposed_text": "Implemented vector search using sentence-transformers embeddings", "confidence": "exact-synonym"}'}

    llm = make_ollama_llm(post=fake_post)
    props = llm(segs, "We need vector search experience")
    assert any(isinstance(p, LlmProposal) and p.jd_keyword and "vector" in p.proposed_text.lower() for p in props)
    assert calls and calls[0]["model"]  # model set, format=json used
    assert calls[0].get("format") == "json"


def test_ollama_llm_returns_empty_on_http_error():
    segs = [_seg("p", r"\item x", ["x"])]

    def boom(url, json_body):
        raise RuntimeError("connection refused")

    props = make_ollama_llm(post=boom)(segs, "need kafka")
    assert props == []


def test_ollama_llm_skips_unparseable_response():
    segs = [_seg("p", r"\item Python microservices", ["python"])]

    def bad(url, json_body):
        return {"response": "not json at all"}

    props = make_ollama_llm(post=bad)(segs, "need python and go")
    assert props == []  # nothing parseable -> no proposals, no raise
```

- [ ] Step 2 — run → FAIL (module missing).
- [ ] Step 3 — implement `resume_llm.py`:
  - env defaults: `HOST = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")`, `MODEL = model or os.getenv("OLLAMA_MODEL", "qwen2.5:14b")`.
  - default `post`: `requests.post(f"{HOST}/api/generate", json=body, timeout=60).json()` (import requests lazily; wrap so a missing server → caught by the caller's try).
  - salient keywords: tokenize `jd_text` (reuse `keyword_map.extract_keywords`), drop those already present in any block text; cap (~8) to bound calls.
  - per keyword: choose the block with max tag/keyword overlap; build a prompt (system: "rewrite truthfully, never invent a tool not in the bullet; map the JD term onto the real bullet; if no truthful mapping exists, say so"); body `{"model": MODEL, "prompt": ..., "stream": False, "format": "json", "options": {"temperature": 0.2}}`.
  - call `post`; parse `resp["response"]` as JSON → `{proposed_text, confidence}`; build `LlmProposal(block_id, jd_keyword, proposed_text, confidence)`. Any exception on a keyword → skip that keyword (continue). Return the collected list.
- [ ] Step 4 — run → PASS (3). Step 5 — **live smoke, skipif Ollama down** (`requests.get(HOST+"/api/tags")` fails → skip): call the real LlmFn on one segment + a real JD keyword, assert ≥0 LlmProposal returned and no raise; run it if Ollama is up.
- [ ] Step 6 — full suite green; commit `feat: Ollama (qwen2.5:14b) adapter producing truthful rephrasing proposals`.

---

### Task 2: wire default engine + real JD keywords + graceful fallback

**Files:** Modify `src/job_dashboard/api/app.py` (default `resume_engine`), `src/job_dashboard/resume/engine.py` (accept salient keywords / stored gaps into suggest); Test `tests/test_resume_llm_wiring.py` (or extend `test_resume_api.py`).

**Interfaces:** `create_app`'s default resume engine uses `make_ollama_llm()` as the `llm`. The `suggest` endpoint passes the job's stored deep-rank `gaps` (from `match_scores`, already computed by `/rank`) as the salient JD keywords when present, so gap chips are real (not "work."/"rga"). If the llm raises/returns [] (Ollama down), `suggest` returns blocks + gaps with zero rephrasings — never 500.

- [ ] Step 1 — failing tests (fake ollama `post` injected via the engine wiring; no real Ollama):
  - suggest with a fake-Ollama engine returns ≥1 rephrasing with a confidence tag, and gaps derived from the job's stored deep-rank gaps (seed a job with `record_llm_evaluation(..., gaps=["Kubernetes"])`; assert "Kubernetes" appears as a gap, not JD stopwords).
  - Ollama-down (fake post raises): suggest returns 200 with `rephrasings: []` and blocks still present (graceful).
- [ ] Step 2 — FAIL. Step 3 — implement: default engine wiring in `create_app`; `suggest` reads `match_scores.gaps` for the job and passes them as the salient keyword source (fall back to JD tokenization when no stored gaps); ensure the propose path is wrapped so an llm error → [] rephrasings.
- [ ] Step 4 — PASS; full suite green. Step 5 — commit `feat: wire Ollama resume engine as default; suggest uses stored deep-rank gaps; graceful Ollama-down fallback`.

---

### Task 3: live end-to-end (controller-driven, not a subagent)

- [ ] Rebuild frontend if needed; restart server (Ollama running).
- [ ] Browser: open a Strong/Good-Fit job → Tailor resume → confirm REAL rephrasing options render with confidence tags (`exact-synonym`/`equivalent`/`transferable`) + real gap chips (not junk) + no crash.
- [ ] Accept a rephrasing, Generate → real tailored PDF; pdftotext confirms the accepted rephrasing wording is present and integrity holds (no fabricated tool). Screenshot proof.
- [ ] Ledger the result.

## Not covered

- Cover letters; Application Agent (later sprints).
- Cloud LLM / hybrid fallback (Ollama-only for now; the `post` seam makes a future swap trivial).
- Fine-tuning; multi-model routing.
