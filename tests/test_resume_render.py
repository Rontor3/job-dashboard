"""Tests for src/job_dashboard/resume/render.py.

Unit tests use an injected fake runner so no real LaTeX toolchain is
required. One live smoke test (skipped only if lualatex is truly absent)
exercises the real lualatex runner end-to-end.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from job_dashboard.resume.segments import Segment


def _segment(text: str, seg_id: str = "seg") -> Segment:
    return Segment(
        id=seg_id,
        kind="skills",
        title=seg_id,
        tags=[],
        tex_path=Path(f"{seg_id}.tex"),
        text=text,
    )


def test_compose_splices_blocks_between_markers_in_order():
    from job_dashboard.resume.render import compose

    blocks = [_segment(r"\section{Alpha} first block", "a"),
              _segment(r"\section{Beta} second block", "b")]
    tex = compose(blocks)

    alpha_idx = tex.index("first block")
    beta_idx = tex.index("second block")
    assert alpha_idx < beta_idx
    assert r"\begin{document}" in tex
    assert r"\end{document}" in tex


def test_compose_uses_custom_template_markers():
    from job_dashboard.resume.render import compose

    template = (
        "PRE\n% RESUME_BODY_START\n% RESUME_BODY_END\nPOST"
    )
    blocks = [_segment("hello block", "a")]
    tex = compose(blocks, template=template)

    assert tex.startswith("PRE")
    assert tex.rstrip().endswith("POST")
    assert "hello block" in tex


def test_render_pdf_uses_injected_runner(tmp_path):
    from job_dashboard.resume.render import render_pdf

    def fake_runner(tex_path, out_dir):
        assert tex_path.exists()
        p = out_dir / "out.pdf"
        p.write_bytes(b"%PDF-1.5 fake")
        return p

    pdf = render_pdf(
        r"\documentclass{article}\begin{document}x\end{document}",
        tmp_path,
        runner=fake_runner,
    )

    assert pdf.read_bytes().startswith(b"%PDF")
    # composed .tex should have been written to out_dir
    tex_files = list(Path(tmp_path).glob("*.tex"))
    assert len(tex_files) == 1
    assert r"\documentclass{article}" in tex_files[0].read_text()


def test_lualatex_path_raises_clear_error_when_missing(monkeypatch):
    from job_dashboard.resume import render

    monkeypatch.setattr(render.shutil, "which", lambda name: None)
    monkeypatch.setattr(render.Path, "exists", lambda self: False)

    with pytest.raises(RuntimeError, match="lualatex not found"):
        render.lualatex_path()


def test_lualatex_path_returns_texbin_path_when_present(monkeypatch):
    from job_dashboard.resume import render

    monkeypatch.setattr(render.Path, "exists", lambda self: True)

    assert render.lualatex_path() == str(render.TEXBIN_LUALATEX)


def test_extract_log_tail_surfaces_latex_error_not_just_trailing_noise(tmp_path):
    from job_dashboard.resume.render import _extract_log_tail

    log = tmp_path / "resume.log"
    noise_before = [f"loading font {i}" for i in range(30)]
    error_block = [
        "! LaTeX Error: Lonely \\item--perhaps a missing list environment.",
        "See the LaTeX manual or LaTeX Companion for explanation.",
    ]
    noise_after = [f"memory stat line {i}" for i in range(60)]
    log.write_text("\n".join(noise_before + error_block + noise_after))

    tail = _extract_log_tail(log)

    assert "LaTeX Error: Lonely" in tail


def test_extract_log_tail_falls_back_to_last_lines_without_error_marker(tmp_path):
    from job_dashboard.resume.render import _extract_log_tail

    log = tmp_path / "resume.log"
    log.write_text("\n".join(f"line {i}" for i in range(100)))

    tail = _extract_log_tail(log)

    assert "line 99" in tail


@pytest.mark.skipif(
    not shutil.which("lualatex") and not Path("/Library/TeX/texbin/lualatex").exists(),
    reason="no lualatex",
)
def test_real_lualatex_smoke(tmp_path):
    from job_dashboard.resume.render import render_pdf

    pdf = render_pdf(
        r"\documentclass{article}\begin{document}Hello, ATS.\end{document}",
        tmp_path,
    )

    assert pdf.exists()
    assert pdf.read_bytes().startswith(b"%PDF")
