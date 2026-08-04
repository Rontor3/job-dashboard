# Résumé Block Editor — Design

**Date:** 2026-08-04
**Status:** Approved (design via interactive prototype), pending spec review
**Depends on:** existing résumé engine (`resume/segments.py`, `engine.py`, `render.py`, `resume_llm.py`), `ResumePanel.jsx`, `/api/jobs/{id}/resume/*`

## Goal

Replace the current post-LLM checkbox résumé flow with an always-visible
**block editor** for **Skills, Experience, and Projects**. Each item is a block
the candidate can **reorder (drag)**, **regenerate** into grounded impact-styled
alternatives (original always kept), **edit** directly, **add**, or **delete** —
and the block order + chosen/edited content is what the generated PDF renders.

Validated with the user through an interactive prototype (v1→v4); this spec
encodes the agreed behavior.

## Non-goals

- Header/Contact, Profile Summary, and Education stay **auto-included** in their
  standard positions — not editable blocks (out of scope for v1).
- No new résumé-rendering engine — reuse `compose` + `lualatex` + the fit/ATS pipeline.
- Regenerate never invents metrics (grounding rule below).

## Architecture

Builds directly on the existing engine, which already: keeps `block_ids` **in
order** through composition, and applies **grounded rephrasings** per block.
Four pieces:

1. `resume/custom_block.py` — turn a user's `{kind, title, bullets}` into
   template-matching **LaTeX** (escaped `\item` list), so edited/added blocks
   render. The one genuinely new engine capability.
2. `resume/resume_llm.py` — `regenerate_block(...)` → 2–3 **grounded**,
   impact-styled alternative bullet-sets for a single block, on demand.
3. `engine.generate_resume` — accept an ordered **layout** (segment blocks and/or
   custom blocks with content) instead of only `block_ids`, composing in order.
4. `ResumePanel.jsx` — the block editor UI (from the prototype), replacing the
   checkbox step; a new `/regenerate-block` call and the richer `generate` payload.

## Block model (API + UI)

An editor block:

```
{ id, kind: "skills"|"experience"|"project",
  title, bullets: [str],
  source: "segment"|"custom",
  segment_id?: str,          // when source == "segment"
  variants: [ {label, bullets} ] }   // "Original" always variants[0]
```

The editor manages only `skills` / `experience` / `project` blocks. On generate,
the fixed blocks (`header-contact`, `summary-main`, `education-*`) are prepended
in their standard order; the editor's ordered blocks follow, grouped by kind
(Skills, then Experience, then Projects — matching résumé convention).

## Backend

### `resume/custom_block.py` — text → LaTeX

```python
def escape_tex(s: str) -> str        # & % $ # _ { } ~ ^ \ → LaTeX-safe
def block_to_tex(kind: str, title: str, bullets: list[str]) -> str
```

`block_to_tex` emits LaTeX matching the existing segments (an item list; for
experience/project a bolded title line then `\begin{itemize} \item … \end{itemize}`;
for skills a compact list). Every user string passes through `escape_tex`, so a
stray `%`/`&`/`$` can't break `lualatex`. Never raises on odd input.

### `resume_llm.regenerate_block`

```python
def regenerate_block(kind, title, bullets, jd_text, profile_text, llm=None,
                     n=2) -> list[list[str]]:
    """Return up to n alternative bullet-sets for one block, tailored to the JD.
    GROUNDED: alternatives may only use facts/metrics present in `bullets` +
    `profile_text`. A number not already supported is replaced with the literal
    token `[add number]` (never invented). Impact-styled: **bold** key terms,
    keep real numbers. Never raises → returns [] on any LLM failure."""
```

Reuses the cover-letter/screening grounding approach: any candidate alternative
whose numeric/technical claim isn't supported by the source bullets or profile is
rewritten with a `[add number]` placeholder rather than emitted. `**bold**`
markup is allowed; the frontend renders it.

### `engine.generate_resume` — ordered layout

Add a `layout` path (keep `block_ids` working for backward-compat). `layout` is
an ordered list; each entry is either `{"segment_id": id}` (use that segment's
tex, still subject to exclusive-group + rephrasings) or
`{"kind","title","bullets"}` (→ `block_to_tex`). Compose in the given order (with
the fixed header/summary/education prepended), then the existing fit → render →
ATS → save pipeline is unchanged.

### API (`resume_routes.py`)

- `POST /api/jobs/{id}/resume/regenerate-block` — body `{kind,title,bullets}` →
  `{alternatives: [[str],…]}` (grounded, via `regenerate_block`).
- `POST /api/jobs/{id}/resume/generate` — accept an optional `layout` (the ordered
  editor blocks with content); when present it drives generation. `block_ids` +
  `accepted_rephrasings` remain accepted for the old path.

## Frontend (`ResumePanel.jsx`)

Replace the checkbox block list with the editor (prototype v4 behavior):

- On open: `suggest` + `segments` → build editor blocks for the `skills` /
  `experience` / `project` kinds (each segment's bullets become `variants[0]`
  "Original"; the suggested subset is pre-included).
- **Drag** to reorder within a kind; order feeds the generate `layout`.
- **Regenerate** a block → `POST /regenerate-block` → show returned alternatives
  as pickable options; Original always kept; picking sets the active variant.
- **Edit** → inline title + bullets (one per line; `**bold**` / `[[number]]`
  render as highlights); saved as a "Your edit" variant, Original preserved.
- **Add** → "add role" / "add project" / "add skill group" → blank block in edit
  mode (`source:"custom"`).
- **Delete** → remove a block.
- Live preview reflects order + each block's active variant.
- **Generate PDF** → `POST /resume/generate` with the ordered `layout` (segment
  blocks send `{segment_id}` when unchanged, or `{kind,title,bullets}` when
  edited/added/alternative-picked). The returned PDF + **ATS report** show as today.

## Error handling

- `block_to_tex` escapes all input; malformed bullets can't break the render.
- `regenerate_block` returns `[]` on LLM failure → UI shows "couldn't generate
  alternatives, keep editing"; the block is unaffected.
- A layout that fails to render (bad LaTeX) surfaces the existing lualatex error;
  the editor state is preserved so the candidate can fix and retry.
- Grounding: unsupported numbers → `[add number]`, never invented.

## Testing

Backend (pytest):
- `escape_tex` handles `& % $ # _ { } ~ ^ \`; `block_to_tex` produces compilable
  LaTeX for experience/project/skills (assert structure + that a `%` in input is
  escaped). A **live lualatex render** test (guarded like the existing ATS live
  test) that a custom block renders to a real PDF.
- `regenerate_block` with a fake llm: returns alternatives; an alternative with an
  unsupported number → `[add number]`; llm raising → `[]` (never raises).
- `generate_resume` with a `layout` mixing a segment block and a custom block →
  composed in order; PDF saved (fake render/ats).
- `/regenerate-block` and `/generate?layout` API round-trips.

Frontend (Vitest):
- Editor renders skills/experience/project blocks from a mocked suggest+segments.
- Regenerate calls `/regenerate-block` and shows alternatives; Original kept.
- Edit saves "Your edit" and preview updates; add creates a block; delete removes.
- Drag reorders; Generate posts the ordered `layout`.

Live e2e (manual): open a Strong-Fit job → editor shows blocks → reorder →
regenerate a block → edit one → add a project → Generate → PDF renders with the
new order/content and a real ATS report.

## Global constraints

- Python 3.11, pytest; React/Vite/Vitest; files under 500 lines.
- **Grounding: never invent numbers** — unsupported → `[add number]`.
- **Original block content is never destroyed** — always `variants[0]`.
- All user text is LaTeX-escaped before rendering (`block_to_tex`).
- Backward-compat: the old `block_ids` generate path keeps working.
- Reuse existing seams: `compose`/`lualatex`/fit/ATS pipeline, `suggest_blocks`,
  segment loading, the grounding approach from cover-letter/screening.
