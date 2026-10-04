# Knowledge bank and long-answer retrieval — design

Date: 2026-10-04 · Status: draft for review · Branch: feat/question-bank

## 1. Problem

The question bank is question-centric: ~87 entries, each holding its own typed answer, profile link or rule. The same
fact therefore lives in several places (notice period is typed into `earliest_start` and read from the profile for
`notice_period`; `last_working_day` has no value at all), and similar-sounding questions get mixed up. Long free-text
answers have no real retrieval: the drafter gets seven résumé units and five empty story slots, and nothing decides
*which* material a given question needs.

## 2. Goals and non-goals

Goals
- Every fact is entered once; any question that needs it follows a change to it.
- Long answers are built from the right material for the question (a mix, not the nearest chunk), without blending
  unrelated projects.
- Everything the candidate knows is editable in the dashboard.
- Retrieval quality is measured before it is trusted.

Non-goals
- No history/versioning of fact values (submitted applications already record what was sent).
- No embedding shortlist over projects until there are more than ~10 (four today).
- No auto-submit changes. Composed and drafted answers stay flagged for review.
- Per-company answers are never stored.

## 3. Decisions already made

- Information enters **both ways**: a Facts page, and facts filed from answers given during runs/tracker (proposed by
  the system, confirmed by the user).
- **Fixed core + open notes**: ~40 named facts for recurring values, free-text notes for the long tail.
- **Ingredients are editable in the dashboard** (they are read-only today).
- **Projects only** get a detailed-answer question: the four Tata AIG projects. Plus the five existing story slots.
- Retrieval is **need-based**: break a question into the needs it contains, retrieve per need, never a single
  similarity search. Shape: plan → retrieve (typed tools, recipe defaults) → write → verify.

## 4. Knowledge model

Three homes for three kinds of knowledge, each held once.

| Home | Holds | Truth level | Editable |
|---|---|---|---|
| **Facts** | short values: notice period, current/expected CTC, total experience, skills with years, location… | exact values; copied or worked out | Facts page |
| **Ingredients** | résumé units (project / role / education): problem, approach, tech, impact, tags, verbatim `source` | `source` is verbatim ground truth, never paraphrased | Ingredients tab; `source` locked behind an explicit unlock |
| **Stories & notes** | the 5 slot stories, one detailed story per project (linked to its ingredient), free notes | the candidate's own words | Stories tab |

Storage: Facts in the existing SQLite bank (new `fact` table; `qbank_entry` stops carrying typed answers). Ingredients stay in
`data/answer_style/ingredients.json`, written by the dashboard atomically with a backup of the previous version, and the
verbatim-search index rebuilds on save. Stories are stored in the bank (`topic='story'`), project stories carry
`ingredient_id`.

Chunk types used at retrieval time: `fact`, `story_slot`, `project_story` (sections: problem, built, tech choices,
hardest part, result, improve), `project_card` (one-line summary derived from ingredient fields), `ingredient_source`,
`role_card`, plus per-job `jd` and `company_research`.

## 5. Short answers (facts)

- Question entries become routers: wordings → needed fact key(s) + format hint. No typed answers on entries.
- Answer path: match entry → fetch facts (same-topic siblings first) → use the value as-is when the fact is the answer
  → otherwise the model composes (dates, formats, option choice) → band `likely`, listed for review.
  (The compose step and slot hint are already built; see §10.)
- Dates: the model returns a day count, code produces the date in the format the question names.
- Never composed: Yes/No statements, sensitive fields, essays.
- Filing: an answer given on the tracker or in a run is parsed into the fact it states, proposed to the user,
  confirmed, stored once; if no fixed fact fits it is stored as a note.
- **Changing a fact** shows a summary before saving: questions it feeds, unsubmitted jobs on the tracker filled with the
  old value (with a re-queue action), and notes/stories/ingredient text that repeat the old value. The fact always
  wins over notes. Submitted applications are untouched.

## 6. Long answers (plan → retrieve → write → verify)

1. **Plan** (one model call): list the needs in the question from a fixed set — `intro`, `one_project`,
   `projects_overview`, `why_company`, `why_role`, `looking_for`, `challenge`, `working_style`, `skills_list`, `other`
   — and pick specifics (which project) from the candidates. Output is validated against the allowed ids. A question
   can hold several needs ("share something about you, what you're looking for, or why X interests you").
2. **Retrieve** by typed tools; each need has a **recipe** with chunk kinds, counts and a size budget:

   | Need | Pulls |
   |---|---|
   | intro | intro story + current-role fact + a project_card for every project |
   | one_project / proud of | best-fit project (by JD) full story + its ingredient_source |
   | why_company | looking_for story + company_research + best-fit project story; at most one more as a card |
   | challenge | the `hardest part` + `result` sections of the best-fit project |
   | looking_for / working_style | the matching story slot |
   | skills_list | skills fact + ingredient tags |
   | other | generic recipe: top chunks across kinds, capped per kind |

   Tools (also exposed through the existing MCP server so Claude Code can call them): `get_facts(keys)`,
   `get_story(slot)`, `list_projects()`, `get_project(id, sections)`, `get_company_context(job)`.
3. **Write** (one call): the prompt contains only the retrieved chunks, labelled by kind, plus the question and the
   field's length limit. Projects not selected are not in the prompt.
4. **Verify:** existing unsupported-claims check; plus a leak check — terms unique to a project that was not retrieved
   (title, distinctive tech) trigger one redraft, then a flag. Length limit enforced.
5. **Review:** always flagged. The card shows which chunks were used and why, with a dropdown to switch the project
   (redrafts). The choice is stored per job so a re-run does not pick differently.

Project stories: one question per project ("Tell me about <project> in detail") with one large box and prompts inside
(problem and why it mattered, what you built, tech and why, hardest part, result with numbers, what you'd improve).
Adding an ingredient of type project creates its question.

## 7. Dashboard

A **Knowledge** area with three tabs: Facts, Ingredients (editable), Stories ("7 of 9 written" progress). A run that
needs a story the user has not written shows the existing "Needs your answer" card on the tracker.

## 8. Evaluation (built first)

Retrieval is measured separately from writing. A labelled set of ~30 long-text questions (the 17 on record plus
questions the user recalls and common ones), each with the chunks it **should** use. Metrics: recall of required
chunks, over-inclusion (chunks pulled that should not be), project-leak rate in drafts. Retrieval changes are accepted
only if these do not regress. Short-answer routing gets the same treatment (the experience/CTC/notice families).

## 9. Phases

Each phase gets its own plan.
1. **Eval set + long-answer pipeline** (plan, tools, recipes, verify) against current ingredients and stories.
2. **Knowledge UI**: editable ingredients, stories tab, project questions.
3. **Facts model + migration**: fact table, routers, filing from answers, change-a-fact summary, collapse duplicates.

## 10. Already built in this branch (uncommitted)

Compose-from-facts step (`qbank_compose.py`), slot hint for the model's entry choice, extra wordings for
`skill_years` / `total_experience_years` / `earliest_start`, trail → ATS-graph promotion, Claude assist, post-fill
screenshots, tracker/queue changes, filled-answer editing. The `earliest_start` typed answer was cleared (old value:
"I can join within 30 days of an offer (30-day notice period).").

## 11. Open questions

- Re-queue on fact change: offer a re-queue button for affected jobs (default) or only list them.
- Reuse of generic stories: let the model tailor to company and job, always reviewed (default), or paste unchanged.
- Notes: whether they can hold structured tags to improve retrieval, or stay plain text.
- Ingredient `source` edits: unlock-with-confirm (default) versus file-only.
- The user to supply 5–10 remembered long-text questions for the eval set.

## 12. Risks

- A 14B local model plans less reliably than a larger one; mitigated by validation, recipe defaults and the eval set, and
  by the option of using `claude -p` for the plan step only.
- Fact and story text can repeat a value; mitigated by the change-a-fact summary, not eliminated.
- 17 real examples is a thin base; the eval set must grow from real runs.
