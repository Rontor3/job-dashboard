"""Resume-tailoring engine: suggest blocks, then generate a tailored PDF.

Orchestrates the pieces built in earlier tasks (``segments``, ``render``,
``ats``, ``fit``, ``keyword_map``, ``db.save_resume``) behind two entry
points:

- ``suggest_blocks`` picks candidate segments for a JD, enforcing that no
  two blocks sharing a non-null ``exclusive_group`` are ever suggested
  together, and proposes truthful keyword rephrasings/gaps.
- ``generate_resume`` takes a human-approved block list and rephrasing set
  and produces the final PDF: it enforces ``exclusive_group`` again (the
  caller's block list is untrusted input), applies rephrasings, composes
  kind-aware LaTeX (item-bearing blocks wrapped in one ``itemize`` per
  section so the document actually compiles), fits to one page, renders the
  FINAL pdf, ATS-checks that exact FINAL pdf (last, on purpose), and saves
  a resumes row.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path
from typing import Callable

from job_dashboard import db
from job_dashboard.resume.custom_block import block_to_tex
from job_dashboard.resume.keyword_map import (
    DeepRankFn,
    GapKeyword,
    LlmFn,
    Rephrasing,
    extract_keywords,
    propose_rephrasings,
)
from job_dashboard.resume.render import compose as render_compose
from job_dashboard.resume.segments import Segment

# LaTeX section title for each segment kind. Kinds sharing a title (the two
# "experience" kinds) are merged into one section/itemize.
_SECTION_TITLES = {
    "summary": "Summary",
    "skills": "Skills",
    "project": "Projects",
    "experience": "Work Experience",
    "experience-framing": "Work Experience",
    "education": "Education",
}

# Canonical résumé section order — Experience is the focus, Skills sit last.
# Sections render in this order regardless of block/layout order.
_SECTION_ORDER = {"Summary": 0, "Education": 1, "Work Experience": 2, "Internship": 3, "Projects": 4, "Skills": 5}


def _is_item_bearing(block: Segment) -> bool:
    """True if this block's own text is a bare ``\\item`` (needs an
    enclosing ``itemize`` or lualatex raises "Lonely \\item")."""
    return block.text.lstrip().startswith("\\item")


def _section_title(block: Segment) -> str:
    override = getattr(block, "section", None)
    if override:
        return override
    return _SECTION_TITLES.get(block.kind, block.kind.replace("-", " ").title())


def _compose_kind_aware(blocks: list[Segment]) -> str:
    """Group ``blocks`` by section and wrap item-bearing ones in ONE
    ``\\begin{itemize}...\\end{itemize}`` per section under the right
    ``\\section{...}``. Non-item-bearing blocks (header, summary) are
    inserted as-is — header content is preamble-style (name/contact
    commands from Task 1's segment library) and summary is prose, neither
    take an itemize wrapper.
    """
    ordered_sections: list[str] = []
    section_blocks: dict[str, list[Segment]] = {}
    passthrough: list[Segment] = []

    for block in blocks:
        # A block belongs to a \section if its kind names one, OR it is a
        # bare \item block (custom kinds still need an enclosing itemize).
        # Everything else (header/contact preamble) passes through as-is.
        if (
            block.kind not in _SECTION_TITLES
            and block.kind != "summary"
            and not _is_item_bearing(block)
        ):
            passthrough.append(block)
            continue
        title = _section_title(block)
        if title not in section_blocks:
            ordered_sections.append(title)
            section_blocks[title] = []
        section_blocks[title].append(block)

    parts: list[str] = [b.text for b in passthrough]
    ordered_sections.sort(key=lambda t: _SECTION_ORDER.get(t, 99))
    for title in ordered_sections:
        section_lines = [f"\\section{{{title}}}"]
        buf: list[str] = []

        def flush():
            if buf:
                section_lines.append("\\begin{itemize}")
                section_lines.extend(buf)
                section_lines.append("\\end{itemize}")
                buf.clear()

        # Preserve block order within a section: consecutive bare-\item
        # blocks (skills categories, projects) share one itemize; a
        # self-contained block (an experience sub-heading + its own itemize,
        # or a summary paragraph) flushes the buffer and is emitted as-is.
        for block in section_blocks[title]:
            if _is_item_bearing(block):
                buf.append(block.text)
            else:
                flush()
                section_lines.append(block.text)
        flush()
        parts.append("\n".join(section_lines))

    return "\n\n".join(parts)


def _build_tex(body: str) -> str:
    """Splice a pre-composed body string into the default template by
    reusing render.compose's marker-splicing (one synthetic wrapper block)
    instead of duplicating that logic here."""
    wrapper = Segment(
        id="_composed_body", kind="_body", title="_body", tags=[],
        tex_path=Path("_composed_body"), text=body,
    )
    return render_compose([wrapper])


def _pdf_page_count(pdf_path: Path) -> int:
    """Best-effort page count via ``pdfinfo``; defaults to 1 (no overflow
    forced) if the tool or file is unavailable so a probing failure never
    turns into an infinite/incorrect cutting loop."""
    try:
        result = subprocess.run(
            ["pdfinfo", str(pdf_path)], capture_output=True, text=True
        )
    except FileNotFoundError:
        return 1
    if result.returncode != 0:
        return 1
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return 1
    return 1


def _make_overflows(
    fixed_blocks: list[Segment],
    all_cuttable_blocks: list[Segment],
    render_pdf: Callable[[str, Path], Path],
    probe_dir: Path,
) -> Callable[[list[str]], bool]:
    """Build the ``overflows(candidate_lines) -> bool`` callable fit_to_page
    needs: render the candidate subset to a probe PDF and check page count.
    Any rendering failure is treated as "fits" — the FINAL render (step e)
    is what actually surfaces a real compile error to the caller.
    """

    def overflows(candidate_lines: list[str]) -> bool:
        candidate_texts = set(candidate_lines)
        kept = [b for b in all_cuttable_blocks if b.text in candidate_texts]
        body = _compose_kind_aware(fixed_blocks + kept)
        tex = _build_tex(body)
        try:
            pdf_path = render_pdf(tex, probe_dir)
            return _pdf_page_count(pdf_path) > 1
        except Exception:
            return False

    return overflows


def _drop_conflicting_block_ids(block_ids: list[str], segments: list[Segment]) -> list[str]:
    """Enforce exclusive_group on a caller-supplied block_id list: the
    first occurrence (in ``block_ids`` order) of each group wins, later
    ones sharing the group are dropped. Raises ``ValueError`` for any
    block_id not found in ``segments`` (validated input boundary)."""
    seg_by_id = {s.id: s for s in segments}
    seen_groups: set[str] = set()
    kept: list[str] = []
    for block_id in block_ids:
        seg = seg_by_id.get(block_id)
        if seg is None:
            raise ValueError(f"unknown block_id: {block_id!r}")
        if seg.exclusive_group is not None:
            if seg.exclusive_group in seen_groups:
                continue
            seen_groups.add(seg.exclusive_group)
        kept.append(block_id)
    return kept


def _drop_conflicting_segments(blocks: list[Segment]) -> list[Segment]:
    """Like ``_drop_conflicting_block_ids`` but operates directly on an
    already-resolved ``Segment`` list (used by the ``layout`` path, where
    custom blocks have no place in the segment library to look up by id):
    the first occurrence (in ``blocks`` order) of each exclusive_group
    wins, later ones sharing the group are dropped."""
    seen_groups: set[str] = set()
    kept: list[Segment] = []
    for seg in blocks:
        if seg.exclusive_group is not None:
            if seg.exclusive_group in seen_groups:
                continue
            seen_groups.add(seg.exclusive_group)
        kept.append(seg)
    return kept


def _resolve_layout(
    layout: list[dict], segments: list[Segment], seg_by_id: dict[str, Segment]
) -> list[Segment]:
    """Build the ordered block list for the ``layout`` composition path:
    fixed segments (header-contact, summary-main, education-*) present in
    ``segments`` are prepended, then each layout entry is resolved to
    either the existing Segment named by ``segment_id`` or a brand-new
    custom Segment built from ``kind``/``title``/``bullets`` via
    ``block_to_tex``."""
    fixed_blocks: list[Segment] = []
    if "header-contact" in seg_by_id:
        fixed_blocks.append(seg_by_id["header-contact"])
    # No Summary section — the candidate's real résumé has none; Education is
    # the only fixed section between the header and the ordered body.
    fixed_blocks.extend(s for s in segments if s.id.startswith("education"))

    mapped_blocks: list[Segment] = []
    for i, entry in enumerate(layout):
        if "segment_id" in entry:
            sid = entry["segment_id"]
            if sid not in seg_by_id:
                raise ValueError(f"unknown segment_id: {sid!r}")
            mapped_blocks.append(seg_by_id[sid])
        else:
            kind, title, bullets = entry["kind"], entry["title"], entry.get("bullets")
            mapped_blocks.append(
                Segment(
                    id=f"custom-{i}", kind=kind, title=title, tags=[],
                    tex_path=None, text=block_to_tex(kind, title, bullets),
                )
            )
    return fixed_blocks + mapped_blocks


def _drop_exclusive_group_losers(
    segments: list[Segment], scores: dict[str, float]
) -> list[Segment]:
    """Among segments sharing a non-null exclusive_group, keep only the
    highest-scoring one; segments with no group always pass through."""
    best_in_group: dict[str, Segment] = {}
    survivors: list[Segment] = []
    for seg in segments:
        if seg.exclusive_group is None:
            survivors.append(seg)
            continue
        current = best_in_group.get(seg.exclusive_group)
        if current is None or scores.get(seg.id, 0.0) > scores.get(current.id, 0.0):
            best_in_group[seg.exclusive_group] = seg
    survivors.extend(best_in_group.values())
    return survivors


def _apply_rephrasings(blocks: list[Segment], accepted: list[Rephrasing]) -> list[Segment]:
    """Replace each block's text with its accepted rephrasing's proposed
    text, if any (last accepted rephrasing for a block wins)."""
    text_by_block = {r.block_id: r.proposed_text for r in accepted}
    return [
        replace(b, text=text_by_block[b.id]) if b.id in text_by_block else b
        for b in blocks
    ]


def _ats_report_dict(ats_report) -> dict:
    return asdict(ats_report) if is_dataclass(ats_report) else dict(ats_report)


def _ats_score_of(ats_report) -> float:
    return ats_report.ats_score if is_dataclass(ats_report) else ats_report["ats_score"]


def suggest_blocks(
    segments: list[Segment],
    jd_text: str,
    deep_rank: DeepRankFn,
    llm: LlmFn | None = None,
    min_score: float = 0.0,
    keywords: list[str] | None = None,
) -> dict:
    """Suggest relevant, non-conflicting blocks for a JD.

    Returns ``{block_ids, rationale, rephrasings, gaps}``. Blocks with a
    deep_rank score at or below ``min_score`` are excluded as irrelevant;
    within each exclusive_group only the highest-scoring survivor remains.

    ``keywords``, when given, is passed through to ``propose_rephrasings``
    as the salient-keyword source (e.g. a job's stored deep-rank gaps)
    instead of crude JD tokenization — see that function's docstring.
    """
    scores = deep_rank(segments, jd_text)
    candidates = [s for s in segments if scores.get(s.id, 0.0) > min_score]
    survivors = _drop_exclusive_group_losers(candidates, scores)
    survivors.sort(key=lambda s: -scores.get(s.id, 0.0))

    proposals = propose_rephrasings(
        survivors, jd_text, deep_rank, llm=llm, keywords=keywords
    )
    rephrasings = [p for p in proposals if isinstance(p, Rephrasing)]
    gaps = [p for p in proposals if isinstance(p, GapKeyword)]

    return {
        "block_ids": [s.id for s in survivors],
        "rationale": {s.id: scores.get(s.id, 0.0) for s in survivors},
        "rephrasings": rephrasings,
        "gaps": gaps,
    }


def render_layout_pdf(
    layout: list[dict],
    *,
    segments: list[Segment],
    render_pdf: Callable[[str, Path], Path],
    out_dir,
) -> dict:
    """Render a SAVED résumé layout straight to a PDF — job-agnostic: no JD,
    no highlighting, no ATS check, no DB write. Composition mirrors the
    ``layout`` path of ``generate_resume`` (fixed header/education prepended,
    then each entry resolved by ``segment_id`` or built as a custom block via
    ``_resolve_layout``) so a version's standalone PDF matches what the editor
    produces for that same layout, minus JD tailoring. ``excluded`` entries
    are dropped, and any ``segment_id`` that no longer exists is skipped rather
    than raising (a saved version must never 500 because the library moved on).
    Returns ``{"pdf_path", "page_count"}``."""
    seg_by_id = {s.id: s for s in segments}
    norm: list[dict] = []
    for entry in layout or []:
        if entry.get("excluded"):
            continue
        sid = entry.get("segment_id")
        kind = entry.get("kind")
        title = entry.get("title") or ""
        bullets = entry.get("bullets") or []
        seg = seg_by_id.get(sid) if sid else None
        # A segment-backed block renders VERBATIM from its .tex unless the user
        # actually edited it (explicit `edited` flag from the editor). This is
        # immune to a segment .tex changing under a saved layout, which the old
        # bullet-by-bullet comparison was not.
        if seg is not None and not entry.get("edited"):
            norm.append({"segment_id": sid})
            continue
        if kind and (bullets or title):
            # A skills/project segment block carries its bold label inside the
            # bullets (**label**); sending the title too would double the heading.
            drop_title = entry.get("source") == "segment" and kind == "skills"
            norm.append({"kind": kind, "title": "" if drop_title else title, "bullets": bullets})
    ordered_blocks = _drop_conflicting_segments(_resolve_layout(norm, segments, seg_by_id))
    tex = _build_tex(_compose_kind_aware(ordered_blocks))
    pdf_path = render_pdf(tex, out_dir)
    return {"pdf_path": str(pdf_path), "page_count": _pdf_page_count(Path(pdf_path))}


def generate_resume(
    conn,
    job_id,
    block_ids: list[str],
    accepted_rephrasings: list[Rephrasing],
    *,
    segments: list[Segment],
    jd_text: str,
    render_pdf: Callable[[str, Path], Path],
    ats_check: Callable,
    fit_to_page: Callable,
    out_dir,
    layout: list[dict] | None = None,
) -> dict:
    """Generate and save a tailored resume PDF. Steps run in this order:
    (a) enforce exclusive_group on block_ids, (b) apply accepted
    rephrasings, (c) fit_to_page (probing candidate subsets via its own
    kind-aware compose), (d) kind-aware compose of the final surviving
    blocks, (e) render FINAL pdf, (f) ats_check the FINAL pdf,
    (g) db.save_resume.

    When ``layout`` is given (an ordered list of ``{"segment_id": id}`` /
    ``{"kind", "title", "bullets"}`` entries) it drives composition
    INSTEAD of ``block_ids``: fixed segments (header-contact, summary-main,
    education-*) present in ``segments`` are prepended, then each layout
    entry is resolved to a real Segment (by id) or a new custom Segment
    (via ``block_to_tex``) — see ``_resolve_layout``. The rest of the
    pipeline, (b) through (g), is unchanged; rephrasings only apply to
    real segments since custom blocks' synthetic ``custom-N`` ids never
    match an accepted rephrasing's ``block_id``. The ``block_ids`` path
    (the ``else`` below) is untouched.
    """
    out_dir = Path(out_dir)
    seg_by_id = {s.id: s for s in segments}

    # (a) exclusive_group enforcement on the caller-supplied selection.
    if layout is not None:
        ordered_blocks = _resolve_layout(layout, segments, seg_by_id)
        ordered_blocks = _drop_conflicting_segments(ordered_blocks)
    else:
        kept_ids = _drop_conflicting_block_ids(block_ids, segments)
        ordered_blocks = [seg_by_id[bid] for bid in kept_ids]

    # (b) apply accepted rephrasings to block text.
    ordered_blocks = _apply_rephrasings(ordered_blocks, accepted_rephrasings)

    # (c) fit-loop operates on cuttable content ("lines" = whole
    # item-bearing block texts, so a cut never leaves a stray \item or
    # breaks the itemize a kept item still needs); fixed (header/summary)
    # blocks are never candidates for cutting.
    # Keep ALL selected blocks — never silently drop the candidate's content to
    # force a single page. The user decides what appears via the editor's
    # include/exclude checkboxes; a fuller résumé may simply run to two pages.
    # (fit_to_page / _make_overflows remain available but are intentionally not
    # applied here so no project/skill/role is dropped without the user's say.)
    final_blocks = ordered_blocks
    cut_texts: list[str] = []

    # (d) kind-aware compose of the final surviving blocks.
    body = _compose_kind_aware(final_blocks)
    tex = _build_tex(body)

    # (e) render the FINAL pdf.
    pdf_path = render_pdf(tex, out_dir)
    page_count = _pdf_page_count(Path(pdf_path))

    # (f) ats_check runs LAST, against the exact FINAL rendered artifact.
    ats_report = ats_check(pdf_path, jd_text)

    # (g) save.
    blocks_used = [b.id for b in final_blocks]
    resume_id = db.save_resume(
        conn, job_id, str(pdf_path), blocks_used,
        _ats_score_of(ats_report), _ats_report_dict(ats_report),
    )

    interview_prep = [
        {"block_id": r.block_id, "jd_keyword": r.jd_keyword, "proposed_text": r.proposed_text}
        for r in accepted_rephrasings
        if r.confidence == "transferable"
    ]

    return {
        "resume_id": resume_id,
        "pdf_path": pdf_path,
        "ats_report": ats_report,
        "blocks_used": blocks_used,
        "cut_lines": cut_texts,
        "page_count": page_count,
        "interview_prep": interview_prep,
    }
