"""Tests for src/job_dashboard/letter/render_letter.py.

Unit tests use an injected fake runner (same seam as
tests/test_resume_render.py) so no real LaTeX toolchain is required. One
live smoke test (skipped only if lualatex is truly absent) exercises the
real render_pdf runner end-to-end.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


def test_render_letter_pdf_splices_escaped_body_into_template(tmp_path):
    from job_dashboard.letter.render_letter import render_letter_pdf

    def fake_runner(tex_path, out_dir):
        assert tex_path.exists()
        p = out_dir / "out.pdf"
        p.write_bytes(b"%PDF-1.5 fake")
        return p

    pdf = render_letter_pdf("Dear Hiring Manager, I am excited.", tmp_path, runner=fake_runner)

    assert pdf.read_bytes().startswith(b"%PDF")

    tex_files = list(Path(tmp_path).glob("*.tex"))
    assert len(tex_files) == 1
    tex = tex_files[0].read_text()

    assert "Dear Hiring Manager, I am excited." in tex
    assert r"\documentclass" in tex
    assert r"\begin{document}" in tex
    assert r"\end{document}" in tex
    assert "[Your Name]" in tex


def test_render_letter_pdf_returns_pdf_path(tmp_path):
    from job_dashboard.letter.render_letter import render_letter_pdf

    def fake_runner(tex_path, out_dir):
        p = out_dir / "letter.pdf"
        p.write_bytes(b"%PDF-1.5 fake")
        return p

    pdf = render_letter_pdf("Body text.", tmp_path, runner=fake_runner)

    assert pdf == tmp_path.resolve() / "letter.pdf"
    assert pdf.exists()


def test_render_letter_pdf_escapes_special_latex_characters(tmp_path):
    from job_dashboard.letter.render_letter import render_letter_pdf

    def fake_runner(tex_path, out_dir):
        p = out_dir / "out.pdf"
        p.write_bytes(b"%PDF-1.5 fake")
        return p

    render_letter_pdf("R&D grew 40% for $5", tmp_path, runner=fake_runner)

    tex_files = list(Path(tmp_path).glob("*.tex"))
    tex = tex_files[0].read_text()

    assert r"R\&D grew 40\% for \$5" in tex
    # No raw unescaped &, %, or $ from the body should leak into the tex.
    body_line = next(line for line in tex.splitlines() if "grew" in line)
    assert "&" not in body_line.replace(r"\&", "")
    assert "%" not in body_line.replace(r"\%", "")
    assert "$" not in body_line.replace(r"\$", "")


def test_latex_escape_handles_all_special_chars():
    from job_dashboard.letter.render_letter import _latex_escape

    escaped = _latex_escape("&%$_#{}")

    assert escaped == r"\&\%\$\_\#\{\}"


def test_latex_escape_joins_paragraphs_with_blank_line():
    from job_dashboard.letter.render_letter import _latex_escape

    escaped = _latex_escape("First paragraph.\n\nSecond paragraph.")

    assert "First paragraph." in escaped
    assert "Second paragraph." in escaped
    assert "\n\n" in escaped


@pytest.mark.skipif(
    not shutil.which("lualatex") and not Path("/Library/TeX/texbin/lualatex").exists(),
    reason="no lualatex",
)
def test_real_lualatex_letter_smoke(tmp_path):
    from job_dashboard.letter.render_letter import render_letter_pdf

    pdf = render_letter_pdf(
        "I am thrilled to apply for this role and bring hedgehog-level focus.",
        tmp_path,
    )

    assert pdf.exists()
    assert pdf.stat().st_size > 0
    assert pdf.read_bytes().startswith(b"%PDF")

    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        import subprocess

        result = subprocess.run(
            [pdftotext, str(pdf), "-"], capture_output=True, text=True
        )
        assert "hedgehog" in result.stdout
