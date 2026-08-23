# Autonomous Career Agent — Design Spec

> **Status:** design, pre-implementation.
> **Scope:** a website-agnostic agent that applies to jobs on companies' **own career pages / independent portals**, driven by an LLM reading the accessibility tree, with a Telegram human-in-the-loop and graduated autonomy. Lives **inside** the existing `job-dashboard` repo as a new package `src/career_agent/`, reusing the dashboard's profile + résumé engine (but **not** its ranking).

---

## 1. Goal & philosophy

Given a **target** (a company career-page URL + optional JD + which résumé), the agent applies on that site: perceive the form → fill known fields → answer questions (grounded) → handle verification gates → attach the tailored CV → get one Telegram approval (early on) → submit → report for feedback. Over a handful of applications it **graduates** from "approve-before-submit" to "fill-and-submit on learned instinct."

Principles:
- **Perception-Action, not brittle selectors.** The agent understands pages semantically via the **accessibility (A11y) tree**, identifying inputs/questions/checkboxes by role + label, so it works on *any* portal, not a hardcoded one.
- **Thinking/Doing split.** The LLM orchestrator ("thinking") calls a small Python execution layer ("doing") over **MCP**. Clean boundary.
- **Anti-hallucination by construction.** Technical facts are stored **verbatim** and copied exactly; only behavioral phrasing is generative. See §4 Tri-Partite Memory.
- **Detect-and-route, never bypass.** Verification gates (CAPTCHA/OTP) are *detected and routed* (auto-solve email OTP, escalate the rest); the system never defeats an anti-bot control. See §7.

## 2. Separation of concerns

```
DASHBOARD (or the user)                 CAREER AGENT
─────────────────────                   ────────────
discovery · ranking · eligibility  ──►  perceive → fill → answer → gate →
= WHICH job to apply to            URL  attach CV → approve → submit → report
                                        = HOW to apply on that site
```

- The agent's **input is a target**: `{ career_page_url, jd_text?, resume_selector? }`.
- The trigger is decoupled: a dashboard event (`new ⚡ external-ATS job → send URL`) **or** a manual CLI/Telegram URL. The agent doesn't know which.
- The agent **reuses** from the dashboard: the **profile** (field values) and the **résumé/CV engine** (tailor + attach). It does **not** use ranking, eligibility scoring, the job queue, or apply-type classification — those decide *whether* to apply and stay in the dashboard.

## 3. Architecture layers

```
LAYER 3 · STORES     Application-state (LangGraph checkpointer) · Tri-Partite memory
LAYER 2 · ORCHESTRATOR  LangGraph StateGraph (durable state machine) + Agent-SDK judgment nodes
LAYER 1 · ROUTERS (MCP)  Browser Action · Memory Access · Human-Loop  (3 master tools)
LAYER 0 · BACKBONE (reuse)  job_dashboard: profile, résumé engine
```

- **LangGraph** = the *predetermined* control skeleton, because submissions are irreversible: nodes + conditional edges + a **checkpointer** (durable state) + **`interrupt()`** (human gates). A crash or a pause resumes at the exact node.
- **Claude Agent SDK** = only the *judgment* nodes (answer a novel question, map an ambiguous field, compose the overview) — a bounded agentic loop inside a node, with a `PreToolUse` hook enforcing guardrails.
- The **3 MCP routers** are the tools both call.

## 4. Tri-Partite Memory (§ anti-hallucination)

| Vault | Store | Holds | Retrieval | Rule |
|---|---|---|---|---|
| **Factual Core** | static JSON | contact, links, **absolute résumé PDF path(s)** | `GET_PROFILE_CHUNK(section)` | JIT chunks; never regenerate a résumé on the fly — pull the exact path and attach |
| **Exact Tech** | SQLite + **FTS5** | verbatim, pre-approved technical descriptions (projects, model architectures) | `EXACT_TECH_SEARCH(keywords)` → `EXACT_QUOTE` | **Copy the quote character-for-character; do not paraphrase** |
| **Semantic Behavior** | **ChromaDB** vectors | past behavioral Q&A + form-field mappings + confidence | `SEMANTIC_MATCH(question_embedding)` | cosine match adapts to wording variance ("notice period" ≈ "earliest availability") |

Reused from the dashboard to seed these: the profile markdown (Factual + Exact seed) and the résumé segments/engine (Exact Tech source; CV generation).

## 5. The Router Pattern (3 master MCP tools)

To keep the orchestrator's context lean and prompt-cache stable, the execution engine exposes exactly **three** endpoints (not 20 fine-grained tools):

1. **Browser Action Router** — `browser_action(action, payload)` where `action ∈ {NAVIGATE, PARSE, CLICK, TYPE, SELECT, UPLOAD, SCREENSHOT, PROBE}`.
2. **Memory Access Router** — `memory_access(op, args)` where `op ∈ {GET_PROFILE_CHUNK, EXACT_TECH_SEARCH, SEMANTIC_MATCH, RECORD_FEEDBACK}`.
3. **Human-Loop Router** — `human_loop(kind, payload)` → Telegram (send overview / await approval / await edit).

Exposed by `mcp_server.py` (FastMCP) = the "doing" boundary.

## 6. Browser perception & resilient automation

- **Playwright, persistent real Chrome profile, non-headless.** Session cookies/login persist across runs (session reuse) and a genuine profile is less bot-flagged *honestly* (it's a real browser you use).
- **Perception = A11y snapshot → Form Model.** `perception.py` turns `page.accessibility.snapshot()` into `[{selector, type, label, required, options, group, guessed_purpose}]`. Re-run **per step** and **after any field reveal** (multi-page + conditional forms just work).
- **Tick-box / question handling:** a "question" is a *grouped* set — single checkbox (consent), checkbox-group (multi-select), radio-group (single-choice), select/combobox, free-text. Grouped by shared `name`/`fieldset`/`role=group`.
- **ATS adapters** (`browser/adapters/`): stable-selector adapters for common portals (greenhouse, lever, ashby, workday); unknown company portals fall back to the generic A11y+LLM parse.
- **Fallback escalation (4 tiers)** for *benign* obstructions (cookie banners, z-index overlays, focus traps, iframes) — **not** anti-bot:
  1. semantic accessible click;
  2. force-click, else JS-dispatched click (for a genuinely obscured real button);
  3. Escape focus-trap / traverse iframes;
  4. multimodal: screenshot → LLM reasons over pixels → self-correct **or** escalate.

## 7. Verification gates — detect & route (with the user-owned seam)

`browser/gate_probe.py` **classifies** the gate (detection only) into a precise enum: `recaptcha_v2_checkbox` · `recaptcha_v2_image` · `recaptcha_v3` · `hcaptcha_*` · `turnstile` · `cloudflare_interstitial` · `otp_email` · `otp_sms` · `text_challenge` · `cleared` · `none`. It never interacts with a challenge widget.

Dispatch (shipped defaults):

```
otp_email               → Gmail MCP auto-fills the code (zero human)
recaptcha_v3 / turnstile→ proceed (invisible, no gate)
every real challenge    → escalate  (screenshot → Telegram → resume on success token)
```

### 7a. Extension point — anti-bot challenge handlers  ⚠️ USER-OWNED

The dispatch map is a `{gate_type → handler}` registry. **This spec ships `escalate` for every genuine challenge type (incl. `cloudflare_interstitial`).** The registry is the *only* seam where a different handler could attach.

**Left intentionally open for the user to implement themselves.** Substituting any challenge slot with a solver/bypass (e.g., a Cloudflare tool or proxy layer) is a **modification the user makes on their own fork**; it is **out of scope for this design and not implemented here.** No module in `career_agent/` imports or references such tools. The shipped code puts `escalate` in that slot and nothing else.

### 7b. Anti-bot posture (all legitimate, no evasion)
- **RateLimiter** (`reliability/rate_limiter.py`) — token bucket: `≤ N apps/hour`, `≤ M/portal/day`, per-domain concurrency = 1, jittered human-pace spacing, exponential backoff on 429. (This single control prevents most challenges from appearing.)
- **PortalState** (`reliability/portal_state.py`) — `{domain → escalation_count, cooldown_until, yield_score}`. After *K* challenges on a portal → cooldown/skip. Low-yield portals (from Gmail signal silence) get deprioritized.
- **Real persistent profile** — the honest fingerprint mitigation.
- **Inbox security-email watch** — an "unusual activity / account locked" email → hard stop + cooldown + alert.

## 8. Graduated autonomy (the confidence matrix)

- Each question-mapping carries a **confidence score** in the Semantic Vault.
- **Approve → increment. Edit → overwrite the stored answer with ground truth + reset.**
- Crossing the **Autonomy Threshold** (default 3 approvals) flips a mapping to `AUTONOMOUS` (filled silently).
- **Field classes (critical guard):**
  - **Stable** (auth, location, notice period, "years with X") → learn the exact value; autonomize freely.
  - **Context-dependent** (salary, "why this company", essays) → the *answer* changes per job → learn the **approach**, **regenerate grounded each time** (JD + Exact Tech vault); never autonomize to a cached string.
- **Substantive attestations** ("I certify true", background-check consent, visa) → **always** flagged to the human, never auto-ticked, regardless of confidence.
- **Submit gate:** a form auto-submits only when **all** its fields are `AUTONOMOUS`. Any novel/low-confidence field → the whole form pings first. **The first real submit on a brand-new form always goes through a Telegram tap.**

## 9. Telegram human-in-the-loop

The review is a **structured text card composed from the agent's own fill decisions** (never a screen-share; cookies are never rendered and never sent):

```
📋 <Company> — <Role>   ·   <portal>   ·   ready to submit
FILLED (profile) ✅ : name / email / phone / work-auth
ANSWERED (review) ⚠️ : "Years Python?"→3 [0.92] · "Why us?"→"…" [0.58]  · résumé: <file>
ATTESTATIONS 🔒 : ☐ background-check consent — NOT ticked
[ ✅ Submit ] [ ✍️ Edit ] [ 🚫 Skip ]
```

- Taps for speed; **free-text replies** (threaded to a line) for nuance. Free text → LLM-parsed into a **scoped rule** (`[Just this company] / [All consulting] / [Everywhere]`) → written to the Semantic Vault.
- Same router carries **approve-before-submit** (early) and **post-submit overview** (after graduation) — the confidence score decides which.
- Optional: a **cropped element screenshot** (`locator.screenshot()`) for visual confirmation of a weird widget — form area only, no browser chrome.

## 10. Gmail inbox (`integrations/gmail_inbox.py`)
Read-only connector on a **dedicated job-only Gmail**. Real-time **OTP** (`wait_for_code(sender, timeout)`) and an **inbound signal stream** (confirmations → tracker, recruiter replies → notify, rejections/silence → yield-score). Email-OTP auto-fills; SMS-OTP escalates.

## 11. CV integration
When a form requires a CV, the agent either (a) **selects** a pre-approved résumé version per role-type, or (b) **generates** a JD-tailored CV via the dashboard's résumé engine (researched-JD → tailored PDF). The Factual Core holds the path; the Browser Router attaches it at the upload step.

## 12. Execution lifecycle (state machine)

```
guard → auth → parse → fill → answer → upload → gate → (consent) → submit → report → feedback
```
- **guard** — trust-ramp: shadow (approve-before-submit) vs autonomous, per field confidences.
- **auth** — open-form: pass · warm session: reuse · new walled portal: interrupt→one-time human step.
- **parse/fill/answer/upload** — Form Model → sources; answer = Agent-SDK node; upload = tailored CV.
- **gate** — §7 classify + dispatch (probe runs after *every* action).
- **submit** — `PreToolUse` hook blocks submit unless the submit-gate (§8) passes.
- **report/feedback** — §9.
Every `interrupt()` persists via the checkpointer and resumes on the Telegram tap / OTP arrival — the flow **suspends, never breaks**.

## 13. Folder layout (`src/career_agent/`)

```
orchestrator/  graph.py · state.py · nodes/ · trust_ramp.py
routers/       browser_router.py · memory_router.py · human_router.py
browser/       runner.py · perception.py · gate_probe.py · adapters/{greenhouse,lever,ashby,workday,generic}.py
memory/        factual_core.py · exact_tech.py · semantic_behavior.py
integrations/  gmail_inbox.py · telegram_bot.py
reliability/   rate_limiter.py · portal_state.py
config/        settings, MCP manifest
mcp_server.py  FastMCP — exposes the 3 routers ("doing" boundary)
run.py         entrypoint: takes a TARGET url (dashboard event OR CLI) → dispatch one graph run
tests/career_agent/
```
Reuse: `from job_dashboard.match … import profile`, `from job_dashboard.resume.engine import …`. **Not** imported anywhere: `proxy_tool.py`, `flare_tool.py`.

## 14. Build order (lean, one testable slice at a time)
1. **Perception harness** — persistent profile → navigate → Form Model + `gate_probe` → fill from `profile.json` → **Telegram approve → submit** on one real company career page. *(This proves the hard core.)*
2. **Routers + MCP server** — wrap step 1 behind the 3 routers.
3. **Tri-Partite memory + graduated autonomy** — confidence matrix, field classes, learning loop.
4. **Gmail OTP + signal stream.**
5. **LangGraph durable orchestration** — checkpointer + `interrupt()`/resume; event trigger from the dashboard.
6. **CV generation node** (researched-JD → tailored PDF).

## 15. Compute & cost model (local-default, Claude-for-judgment)

Hardware target: **Apple M4 Pro, 24 GB unified memory**, Ollama on Metal. The agent keeps a **persistent Chrome context resident** while working (~2-4 GB), so the local model is sized to leave browser headroom — never to fill RAM.

**Two-tier reasoning substrate** (model-agnostic behind the routers):

| Tier | Handler | Handles | Why |
|---|---|---|---|
| **Local workhorse** | Ollama **`qwen3:14b`** | form → Form Model JSON · stable field mapping · templated review cards · routine short text | high-volume, low-stakes, free; fits beside the resident Chrome |
| **Judgment** | **Claude** (Pro via Agent SDK, or API) | novel/ambiguous screening questions · low-confidence field disambiguation · quality-critical free-text (e.g., "why this company") | low-volume, high-stakes; worth the stronger model |

**Routing rule — volume + stakes, NOT writing-vs-reasoning.** An essay is "writing" yet high-stakes → Claude. A stable field map is trivial → local. The node decides by `(confidence, stakes)`, not by task type.

**Cost guards:**
- **Hard cap on Claude calls per application** (default `≤ 4`); on overflow, fall back to the local model rather than exceed the cap. Claude Pro's allowance is modest and shared with the user's coding use — a single bad run must not burn it.
- **Graduated autonomy compounds the saving:** an approved field stops calling *any* LLM (§8), so Claude calls per application trend toward **zero** as the agent learns a portal/company.
- Local tier has **no metered cost**; the bulk of every application runs free.

## 16. Global constraints
- Reasoning substrate is model-agnostic behind the routers (Agent SDK / API / local Ollama — an honest, licensed compute source; **not** circumventing a subscription's billing).
- **No evasion in-tree:** the system detects-and-routes verification gates and never defeats an anti-bot control; the sole seam (§7a) ships `escalate` and is user-owned.
- **No auto-submit on an unproven form** — first real submit per form always taps through Telegram.
- **Substantive attestations always flagged**, never auto-answered.
- The review is composed data, never a screen/session share.
