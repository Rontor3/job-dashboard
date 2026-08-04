"""Tests for engine.generate_resume's ordered ``layout=`` path (Task 3).

Uses the same fake render_pdf / ats_check / fit_to_page pattern as
tests/test_resume_engine.py so no real LaTeX/pdftotext toolchain is
required.
"""

from __future__ import annotations

from pathlib import Path

from job_dashboard import db
from job_dashboard.models import JobListing
from job_dashboard.resume.ats import AtsReport
from job_dashboard.resume.engine import generate_resume
from job_dashboard.resume.fit import FitResult
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
        _segment("header-contact", "header", r"\name{A}{B}"),
        _segment("summary-main", "summary", "Experienced engineer."),
        _segment("skills-a", "skills", r"\item \textbf{Programming}: Python, SQL"),
    ]


def _fake_render_pdf(calls):
    def render_pdf(tex, out_dir):
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


def test_generate_resume_layout_composes_real_segment_and_custom_block_in_order(tmp_path):
    """A layout mixing one real segment_id + one custom project block must
    compose BOTH, in order, with the custom block's \\item \\textbf{...}
    LaTeX reaching the final composed tex."""
    conn = db.init_db(tmp_path / "t.db")
    job_id = _seed_job(conn)
    segments = _base_segments()
    layout = [
        {"segment_id": "skills-a"},
        {"kind": "project", "title": "Rocket", "bullets": ["did x"]},
    ]
    calls = []

    result = generate_resume(
        conn, job_id, [], [],
        segments=segments, jd_text="Looking for engineer.",
        render_pdf=_fake_render_pdf(calls),
        ats_check=_fake_ats_check(calls),
        fit_to_page=_identity_fit_to_page(calls),
        out_dir=tmp_path / "out",
        layout=layout,
    )

    assert result["resume_id"] > 0
    tex_path = Path(result["pdf_path"]).parent / "resume.tex"
    tex = tex_path.read_text()

    # Both blocks composed: the real skills segment AND the custom
    # project block's \item \textbf{...} line reach the final tex.
    assert r"\textbf{Programming}: Python, SQL" in tex
    assert r"\item \textbf{Rocket}: did x" in tex

    # Order preserved: the real segment's content precedes the custom one.
    assert tex.index("Programming") < tex.index("Rocket")

    assert "skills-a" in result["blocks_used"]
    assert "custom-1" in result["blocks_used"]
    # Fixed segments (header-contact, summary-main) present in `segments`
    # are prepended automatically.
    assert "header-contact" in result["blocks_used"]
    assert "summary-main" in result["blocks_used"]


def test_generate_resume_layout_prepends_fixed_segments_only_if_present(tmp_path):
    """Fixed segments not present in `segments` are simply skipped, no
    error."""
    conn = db.init_db(tmp_path / "t.db")
    job_id = _seed_job(conn)
    segments = [_segment("skills-a", "skills", r"\item \textbf{Programming}: Python, SQL")]
    layout = [{"segment_id": "skills-a"}]
    calls = []

    result = generate_resume(
        conn, job_id, [], [],
        segments=segments, jd_text="role",
        render_pdf=_fake_render_pdf(calls),
        ats_check=_fake_ats_check(calls),
        fit_to_page=_identity_fit_to_page(calls),
        out_dir=tmp_path / "out",
        layout=layout,
    )

    assert result["blocks_used"] == ["skills-a"]
