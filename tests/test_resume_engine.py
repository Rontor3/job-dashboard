"""Tests for src/job_dashboard/resume/engine.py.

Unit tests inject fake render_pdf / ats_check / fit_to_page so no real
LaTeX/pdftotext toolchain is required, matching the DI pattern used by
render.py, ats.py, and fit.py's own test suites.
"""

from __future__ import annotations

from pathlib import Path

from job_dashboard import db
from job_dashboard.models import JobListing
from job_dashboard.resume.ats import AtsReport
from job_dashboard.resume.engine import generate_resume, suggest_blocks
from job_dashboard.resume.fit import FitResult
from job_dashboard.resume.keyword_map import Rephrasing
from job_dashboard.resume.segments import Segment


def _segment(seg_id, kind, text, exclusive_group=None, tags=None):
    return Segment(
        id=seg_id, kind=kind, title=seg_id, tags=tags or [],
        tex_path=Path(f"{seg_id}.tex"), text=text, exclusive_group=exclusive_group,
    )


def _seed_job(conn):
    job = JobListing(
        source="src1", title="AI Engineer", company="Acme",
        job_url="https://x.com/1", description="desc",
    )
    db.insert_job(conn, job)
    return conn.execute("SELECT id FROM jobs ORDER BY id DESC").fetchone()[0]


def _base_segments():
    return [
        _segment("header", "header", r"\name{A}{B}"),
        _segment("summary", "summary", "Experienced engineer."),
        _segment("skills-a", "skills", r"\item \textbf{Programming}: Python, SQL"),
        _segment(
            "exp-full", "experience",
            r"\item{\cventry{2023--Present}{Data Scientist}{Acme}{}{}{}}",
            exclusive_group="acme-role",
        ),
        _segment(
            "exp-framing", "experience",
            r"\item{\cventry{2023--Present}{Analyst framing}{Acme}{}{}{}}",
            exclusive_group="acme-role",
        ),
    ]


def _fake_render_pdf(calls):
    def render_pdf(tex, out_dir):
        # Mirrors render.render_pdf's real contract: write the composed
        # .tex alongside the produced pdf, so callers can inspect it.
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "resume.tex").write_text(tex)
        pdf_path = out_dir / "resume.pdf"
        pdf_path.write_bytes(b"%PDF-1.5 fake")
        calls.append(("render", pdf_path))
        return pdf_path
    return render_pdf


def _fake_ats_check(calls):
    def ats_check(pdf_path, jd_text):
        calls.append(("ats_check", pdf_path))
        return AtsReport(
            ats_score=88, contact_ok=True, reading_order_ok=True,
            keyword_coverage=0.9, missing_keywords=[], warnings=[],
        )
    return ats_check


def _identity_fit_to_page(calls):
    def fit_to_page(lines, jd_keywords, overflows):
        calls.append(("fit_to_page", tuple(lines)))
        return FitResult(kept=list(lines), cut=[])
    return fit_to_page


def test_generate_resume_writes_row_and_returns_report_with_interview_prep(tmp_path):
    conn = db.init_db(tmp_path / "t.db")
    job_id = _seed_job(conn)
    segments = _base_segments()
    block_ids = ["header", "summary", "skills-a", "exp-full"]
    accepted = [
        Rephrasing(
            block_id="skills-a",
            original_text=segments[2].text,
            proposed_text=r"\item \textbf{Programming}: Python, SQL, applied ML",
            jd_keyword="ml",
            confidence="transferable",
            needs_interview_prep=True,
        )
    ]
    calls = []

    result = generate_resume(
        conn, job_id, block_ids, accepted,
        segments=segments, jd_text="Looking for ML engineer.",
        render_pdf=_fake_render_pdf(calls),
        ats_check=_fake_ats_check(calls),
        fit_to_page=_identity_fit_to_page(calls),
        out_dir=tmp_path / "out",
    )

    assert result["resume_id"] > 0
    assert Path(result["pdf_path"]).exists()
    assert result["ats_report"].ats_score == 88
    assert set(result["blocks_used"]) == {"header", "summary", "skills-a", "exp-full"}
    assert result["cut_lines"] == []
    assert result["interview_prep"] == [
        {"block_id": "skills-a", "jd_keyword": "ml", "proposed_text": accepted[0].proposed_text}
    ]

    saved = db.get_resume(conn, result["resume_id"])
    assert saved is not None
    assert saved["job_id"] == job_id
    assert saved["pdf_path"] == str(result["pdf_path"])
    assert set(saved["blocks_used"]) == {"header", "summary", "skills-a", "exp-full"}
    assert saved["ats_score"] == 88

    # The rephrased text, not the original, must be what actually got used.
    tex_path = Path(result["pdf_path"]).parent / "resume.tex"
    assert "applied ML" in tex_path.read_text()


def test_generate_resume_exclusive_group_keeps_at_most_one(tmp_path):
    """Two blocks sharing exclusive_group='acme-role' are both requested;
    generate_resume must drop the conflict rather than emit both."""
    conn = db.init_db(tmp_path / "t.db")
    job_id = _seed_job(conn)
    segments = _base_segments()
    block_ids = ["header", "exp-full", "exp-framing"]  # exp-full listed first
    calls = []

    result = generate_resume(
        conn, job_id, block_ids, [],
        segments=segments, jd_text="Data Scientist role.",
        render_pdf=_fake_render_pdf(calls),
        ats_check=_fake_ats_check(calls),
        fit_to_page=_identity_fit_to_page(calls),
        out_dir=tmp_path / "out",
    )

    assert "exp-full" in result["blocks_used"]
    assert "exp-framing" not in result["blocks_used"]


def test_suggest_blocks_exclusive_group_keeps_at_most_one():
    segments = _base_segments()

    def fake_deep_rank(segs, jd):
        # exp-full scores higher than exp-framing; everything else neutral.
        return {s.id: (2.0 if s.id == "exp-full" else 1.0) for s in segs}

    result = suggest_blocks(segments, "Data Scientist role.", fake_deep_rank, llm=None)

    assert "exp-full" in result["block_ids"]
    assert "exp-framing" not in result["block_ids"]
    assert isinstance(result["gaps"], list)
    assert isinstance(result["rephrasings"], list)


def test_ats_check_runs_last_against_final_rendered_pdf(tmp_path):
    """ats_check must be called with the pdf render_pdf actually produced
    (after the fit-loop step), not called before render or on some other
    intermediate artifact."""
    conn = db.init_db(tmp_path / "t.db")
    job_id = _seed_job(conn)
    segments = _base_segments()
    block_ids = ["header", "summary", "skills-a"]
    calls = []

    result = generate_resume(
        conn, job_id, block_ids, [],
        segments=segments, jd_text="Python role.",
        render_pdf=_fake_render_pdf(calls),
        ats_check=_fake_ats_check(calls),
        fit_to_page=_identity_fit_to_page(calls),
        out_dir=tmp_path / "out",
    )

    kinds = [c[0] for c in calls]
    # No auto-cut: all selected blocks are kept (fit_to_page is not applied so
    # the candidate's content is never silently dropped). render, then ats_check.
    assert "fit_to_page" not in kinds
    assert kinds.index("render") < kinds.index("ats_check")

    render_pdf_path = next(c[1] for c in calls if c[0] == "render")
    ats_pdf_path = next(c[1] for c in calls if c[0] == "ats_check")
    assert ats_pdf_path == render_pdf_path == Path(result["pdf_path"])
