# Question Bank — faithful answer retrieval for application forms

Date: 2026-09-26 · Status: design approved, pending spec review
Supersedes (answer recall only): `memory/learned_answers.py`, `memory/semantic_behavior.py`,
`orchestrator/standard_answers.py`

## Problem

Answer recall is vague and sometimes wrong. Evidence from `data/jobs.db` and
`data/semantic_behavior` on 2026-09-26:

1. **Junk keys.** `learned_answers` (20 rows) holds keys `"yes"`, `"no"`,
   `cards[<uuid>][field3]` — option text / input names captured instead of the
   question. The Chroma vault (7 rows) holds the same junk.
2. **Purpose collision.** Rule 1 of `AnswerMemory._lookup` reuses the newest
   answer with the same `purpose`. "Are you Hispanic/Latino?" and "Please
   identify your race" share `purpose=ethnicity`, so one can be answered with
   the other's value.
3. **Context baked into literals.** "Interviewed at Anthropic before?" /
   "Located in Canada?" stored as fixed strings; wrong or missed for another
   company/country.
4. **Cold start.** Nothing is known until asked; only ~9 purposes in
   `standard_answers.py` are pre-answered.
5. **No evidence.** `application_qa` is empty, so thresholds are unmeasured.

## Goals

- Most standard questions answered on first contact with an ATS (seeded bank).
- Retrieval is faithful: **the LLM may choose which question this is and which
  option to click; it never writes a bank answer.** Values come verbatim from
  the bank, the profile, the job row, or a deterministic rule.
- Every weak result becomes a flag, never a silent fill.
- Thresholds are calibrated from data and re-tuned from real-run outcomes.

## Non-goals

- Essays (free-text motivation / behavioral). They stay with the judgment tier
  + `ingredients.json`, always flagged.
- Attestations / agreements. Existing attestation policy unchanged; never stored.
- Repeating employer/education blocks. Stay with `profile_resolver`.

## 1. Storage

Two tables in `data/jobs.db`:

**`qbank_entry`** — one per distinct question.

| column | meaning |
|---|---|
| `id` | slug, e.g. `sponsorship_required`, `work_location`, `home_address` |
| `question` | canonical wording |
| `topic` | UI group: work_auth · compensation · location · demographics · experience · misc |
| `atype` | `bool` · `choice` · `text` · `number` · `date` |
| `answer` | your canonical value (NULL = unanswered, or when `rule`/`profile_ref` set) |
| `profile_ref` | dotted path into `application_profile` (e.g. `contact.gender`) — read, never copied |
| `rule` | name of a function in `qbank_rules.py` (e.g. `local_or_escape`) |
| `slots` | JSON list: any of `company`, `country`, `skill`, `city` |
| `synonyms` | JSON `{canonical_value: [option texts seen/accepted]}` |
| `shape` | expected text shape: address · url · email · phone · number · postcode · date · NULL |
| `status` | `active` · `superseded` |
| `updated_at` | ISO timestamp |

**`qbank_wording`** — every confirmed phrasing.

| column | meaning |
|---|---|
| `norm` | normalized wording (PK; same normalization as `qa_store.norm_key`) |
| `entry_id` | FK → `qbank_entry.id` |
| `vec` | BLOB, float32 MiniLM embedding |
| `source` | `seed` · `human` · `kept` (an auto-fill the human kept) |

Precedence of an entry's value: `rule` > `profile_ref` > `answer`.

**Seed:** `data/qbank_seed.json` — ~100 entries (question, topic, atype, slots,
rule/profile_ref, shape, 2–3 wordings, synonyms). **No answers** — safe to
commit. Answers are entered on the dashboard and live only in `jobs.db`.

**Migration (one-off):** usable `learned_answers` rows (veteran, disability,
race, Hispanic, English level, start date, notice) become wordings + answers of
their seed entries. Junk rows (label < 3 meaningful tokens, option-like, or
`name[...]`-shaped) are dropped. Standing values from the
`career-agent-user-answers` memory become seed answers; that memory is updated
to point at `qbank_entry`.

## 2. Retrieval pipeline (per field)

```
Field (label, description, kind, options, input_type, autocomplete)
  1 clean      junk label → unknown
  2 escape     split instruction literal ("type \"relocating\"") off the question
  3 match      exact wording → embedding shortlist → LLM pick-or-none → polarity
  4 answer     rule / profile_ref / answer, slots filled from job row
  5 shape      value fits declared/inferred shape
  6 fit        canonical value → one of the page's options
  → band: CONFIDENT fill · LIKELY fill+flag · NONE blank+flag
```

**1 Clean.** Question text = label + description (helper text). Reject as
unknown if fewer than 3 non-stop tokens, equal to one of its own options, or
matches `^\w+\[.*\]` (input name).

**2 Escape word.** Regex over label + description:
`\b(type|enter|write|put|respond with)\b[^"“']{0,20}["“']([^"”']{2,30})["”']`.
On hit: `escape = group(2)` and the instruction sentence is removed before
matching. The escape word is taken **from the page**, never stored per company.
Any entry's rule may return it.

**3 Match.**
- **Exact:** `norm` lookup in `qbank_wording` → score 1.0.
- **Shortlist:** cosine over all active wordings, best score per entry, top 3.
- **Bands** on the top score `s1` and gap `s1 - s2`:
  - `s1 < FLOOR` → NONE (result discarded; unknown question).
  - `s1 ≥ HIGH` and gap ≥ `MARGIN` → CONFIDENT candidate.
  - otherwise → LLM pick: prompt with the question and the 3 canonical
    questions; reply must be one of their ids or `none` (validated; anything
    else = `none`). Picked → LIKELY. `none` → NONE.
- **Polarity guard:** tokens {`not`, `no`, `without`, `never`, `ever`,
  `require`, `need`} — if the set present in the question differs from the
  matched wording's set, cap the band at LIKELY.
- `form_model.guess_purpose` is **not** an answer key; it may break ties only.
- `FLOOR`, `HIGH`, `MARGIN` start from `scripts/qbank_calibrate.py`;
  `HIGH` is exposed as the existing dashboard setting `answer_confidence_min`
  (0–100 → 0.0–1.0).

**4 Answer.** Slots filled from the `jobs` row for this run (`company`,
location → `city`/`country`) and from regex against the question
(`country` list, profile skills). Rules are plain Python in `qbank_rules.py`:
- `local_or_escape`: job city unknown → flag; in `local_cities` entry → home
  address; else → escape word (or flag if none).
- `empty_or_escape`: value empty and escape present → escape word.
- `years_in_skill(skill)`: from `candidate_profile` / stored per-skill answers.
- `country_is_home(country)`: "Yes" iff country is India (from
  `standard_answers` work-auth logic, including its both-countries → flag case).
- `company_in_list(company)`: "Yes" iff company in a stored list, else "No".
Unanswered entry (NULL answer, no rule/profile value) → NONE.

**5 Shape.** Expected shape = entry `shape`, else inferred from
`input_type` (email/tel/url/number/date), `autocomplete`
(street-address/address-line1/postal-code/tel/email/url), else label words.
If an escape word is present, the escape word itself also passes. Stdlib
checks (regex/len) per shape. Fail → cap at LIKELY. No clue → pass.

**6 Fit to options** (choice/bool fields): normalized exact option text →
entry `synonyms[value]` → `judgment.match_value_to_option` (LLM limited to
the page's options). No fit → NONE.

**Logging:** every field writes `application_qa` with `retrieval_kind`
(exact/shortlist/llm/none), `retrieved_qkey` (entry id), `retrieval_score`,
`candidates_json` (top 3 + gates), `confidence`, `status`
(`filled` / `needs_answer`).

## 3. Human review and learning

Below-CONFIDENT fields are filled-and-flagged (LIKELY) or left blank (NONE) and
surface before submit (submit stays human-gated). Answering one offers:

- **New entry** → creates `qbank_entry` + wording (`source=human`).
- **Another wording of [entry ▾]** → adds wording; next time it's an exact hit.
- **Just this application** → stored only in `application_qa`; bank untouched.

A LIKELY fill the human keeps → wording added (`source=kept`). An edit →
outcome `edited`, answer is not auto-overwritten; the review asks whether the
entry's answer changed or the match was wrong (re-point to correct entry).

The bank grows **only** from human-confirmed choices.

## 4. Dashboard (existing components, repointed)

| Component | Becomes |
|---|---|
| `AnswersTab.jsx` | The questionnaire: entries grouped by `topic`, "N unanswered" counter, answer editor, wordings, asked-in count. Chroma trust badge removed. |
| `QuestionsPanel.jsx` | Pre-submit flags per job, with the three-way "save as" choice. |
| `AnswersUsed.jsx` | Adds matched entry + score per row; "wrong" can re-point to another entry. |
| `RetrievalPanel.jsx` | Adds edit-rate by score band; keeps `answer_confidence_min` control. |

API: existing routes in `api/qa_routes.py` keep URLs, read/write new tables.
New: `GET /api/qbank/entries?search=` for the entry picker. Telegram collector
reply gains the same "save as" choice.

## 5. What happens to existing stores

| Store | Fate |
|---|---|
| `learned_answers.py` | unwired, kept; superseded in ATS graph |
| `semantic_behavior.py` + `data/semantic_behavior` | unwired, kept; superseded |
| `standard_answers.py` | logic moved to seed entries + `qbank_rules.py`; superseded |
| `application_profile` / `factual_core.py` | unchanged; read via `profile_ref` |
| `candidate_profile.py` / `profile_resolver.py` | unchanged; repeating blocks still go here |
| `exact_tech.py` / `ingredients.json` | unchanged; essays |
| `application_qa` / `qa_store.py` | unchanged schema; now the calibration evidence |
| `memory_router.py` | `SEMANTIC_MATCH` / `RECORD_FEEDBACK` dispatch to qbank |
| `retrieval_trace.py` | rewritten to explain qbank matches |

## 6. Code layout

New:
- `src/career_agent/memory/qbank.py` — tables, seed load, wording add, migration.
- `src/career_agent/memory/qbank_match.py` — steps 1–3, 5–6 + bands.
- `src/career_agent/memory/qbank_rules.py` — rules + shape checks.
- `data/qbank_seed.json` — seed, no answers.
- `scripts/qbank_calibrate.py` — hold-one-wording-out per entry; prints score
  distributions for correct vs wrong matches and suggested `FLOOR`/`HIGH`/`MARGIN`,
  plus top-1 accuracy.

Reused: Chroma's ONNX MiniLM embedding function (vectors stored in
`qbank_wording.vec`, numpy cosine — few hundred rows); local LLM client and
`match_value_to_option` from `judgment.py`.

Edited: `browser/perception.py` + `form_model.Field` (add `input_type`,
`autocomplete`); `orchestrator/graph.py` + `apply.py` (replace
`AnswerMemory.recall` and `_semantic_split` with one qbank call);
`qa_store.py`, `api/qa_routes.py`, the four components above;
`docs/career-agent/ats-graph.json` (supersede markers).

## 7. Testing

- Unit (pure, no browser): escape-word split, junk-label filter, shape checks,
  each rule, polarity guard, band assignment, LLM pick validation (non-id reply
  → `none`), option fit order.
- Calibration script doubles as the retrieval regression check (top-1 accuracy
  must not drop).
- Dry run on fixtures `greenhouse_labels.html`, `entry_form.html` to confirm
  wiring.

## 8. Build order (each step green + committed)

1. Store + seed file + migration.
2. Rules + shape checks.
3. Matching + calibration script → initial thresholds.
4. Perception `input_type` / `autocomplete`.
5. Wire into run, replacing old tiers.
6. Dashboard components + API.
7. User answers questionnaire → first real dry run → read edit-rate by band.

## Known limits

- A confidently **wrong** match (high score, wrong entry) passes the floor;
  mitigated by margin, polarity, shape, and pre-submit review, and measured via
  kept/edited outcomes — not eliminated.
- Shape check only helps where the page gives a clue.
- Job city parsing depends on the `jobs.location` string; unparseable → flag.

## Follow-up (separate task)

Enrich `data/answer_style/ingredients.json` for essays: per project add
context/role, hard part, decision + rejected alternatives, result, lesson; plus
3–4 non-project stories (why moving, what next, a disagreement, a failure).
Content only; no code change.
