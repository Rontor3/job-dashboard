"""JD-tailored CV node for the career agent graph.

Runs after reach (JD text is in state) and before perceive (form reading).
Selects the highest-overlap resume segments, renders a tailored PDF via
lualatex, and stores the path in config so fill_node uses it for uploads.

Falls back silently to the existing resume_pdf on any error so a LaTeX
failure never blocks the application.
"""
from __future__ import annotations

from pathlib import Path


def _keyword_deep_rank(segs, jd_text: str) -> dict[str, float]:
    """Keyword-overlap scorer: counts how many JD tokens appear in each segment."""
    from job_dashboard.resume.keyword_map import extract_keywords
    kws = {k.lower() for k in extract_keywords(jd_text)}
    return {
        s.id: float(sum(1 for kw in kws if kw in s.text.lower()))
        for s in segs
    }


def tailor_cv_node(state, config) -> dict:
    """Generate a JD-tailored resume PDF and stash it in config for fill_node.

    Opt-in only (--tailor-cv): the default upload is the candidate's own résumé. Runs once per application (tailor_cv_done guard prevents re-run on the
    perceive→fill→advance→perceive loop). No-ops silently when:
    - jd_text is absent or too short
    - rendering already ran this application
    - an exception occurs (existing resume_pdf remains intact)
    """
    jd_text = (state.get("jd_text") or "").strip()
    c = config["configurable"]

    if not c.get("tailor_cv"):
        return {}                              # the résumé the candidate supplied stays; nothing generated replaces it

    if len(jd_text) < 50:
        return {}
    if c.get("tailor_cv_done"):
        return {}

    try:
        from job_dashboard.resume.segments import load_segments
        from job_dashboard.resume.engine import suggest_blocks, render_layout_pdf
        from job_dashboard.resume.render import render_pdf

        segments = load_segments()
        suggestion = suggest_blocks(segments, jd_text, _keyword_deep_rank, llm=None)
        block_ids = suggestion.get("block_ids") or []
        if not block_ids:
            print("[tailor_cv] suggest_blocks returned no blocks — keeping existing CV", flush=True)
            return {}

        layout = [{"segment_id": bid} for bid in block_ids]
        out_dir = Path(c.get("resume_out_dir") or "data/resumes/tailored").resolve()
        result = render_layout_pdf(layout, segments=segments, render_pdf=render_pdf, out_dir=out_dir)

        # employers see ONE file name on every application: the tailored PDF goes out under the same
        # '<Full_Name>_Resume.pdf' as the supplied one (in its own folder per run so it never overwrites that one)
        import re as _re
        import shutil as _sh
        prof = c.get("profile")
        stem = "_".join(_re.findall(r"[A-Za-z0-9]+", (prof.contact.get("full_name") if prof else "") or "")) or "Resume"
        named = Path(result["pdf_path"]).parent / "upload" / f"{stem}_Resume.pdf"
        named.parent.mkdir(parents=True, exist_ok=True)
        _sh.copy2(result["pdf_path"], named)
        c["resume_pdf"] = str(named)
        c["tailor_cv_done"] = True
        print(
            f"[tailor_cv] {len(block_ids)} blocks → {result['page_count']}p PDF: {result['pdf_path']}",
            flush=True,
        )
    except Exception as exc:
        print(f"[tailor_cv] skipped ({type(exc).__name__}: {exc})", flush=True)

    return {}
