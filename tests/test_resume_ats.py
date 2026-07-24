"""Tests for src/job_dashboard/resume/ats.py.

Unit tests inject a fake ``extract`` so no ``pdftotext`` binary is required.
One live test renders a real PDF via Task 3's ``render_pdf`` (real lualatex
runner) and runs ``ats_check`` against it with the real ``pdftotext``
subprocess extractor — skipped only if lualatex is truly absent.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from job_dashboard.resume.ats import ats_check

CLEAN_RESUME_TEXT = """
John Doe
john.doe@example.com | +1 555-123-4567

Experience
Built scalable Python services using Docker and Kubernetes for backend systems.

Education
BS Computer Science, State University.

Skills
Python, Docker, Kubernetes, AWS, PostgreSQL.
"""

JD_TEXT = (
    "Looking for a backend engineer with strong Python and Docker and "
    "Kubernetes experience. AWS and PostgreSQL a plus."
)

GARBLED_TEXT = ("�" * 200) + "no contact info here just noise at all"


def test_clean_resume_scores_high_with_contact_and_coverage():
    report = ats_check("fake.pdf", JD_TEXT, extract=lambda p: CLEAN_RESUME_TEXT)

    assert report.contact_ok is True
    assert report.keyword_coverage > 0.5
    assert report.reading_order_ok is True
    assert report.ats_score > 70
    assert report.warnings == []


def test_garbled_hostile_text_scores_low_with_warning():
    report = ats_check("fake.pdf", JD_TEXT, extract=lambda p: GARBLED_TEXT)

    assert report.contact_ok is False
    assert report.keyword_coverage < 0.3
    assert "possible garbled glyphs" in report.warnings
    assert report.ats_score < 30


def test_missing_keywords_lists_jd_terms_absent_from_resume():
    resume_text = "Contact: jane@example.com, phone 555-999-8888. I know Python well."
    jd_text = "We need Python and Rust and Kubernetes and Terraform experience."

    report = ats_check("fake.pdf", jd_text, extract=lambda p: resume_text)

    assert "rust" in report.missing_keywords
    assert "kubernetes" in report.missing_keywords
    assert "terraform" in report.missing_keywords
    assert "python" not in report.missing_keywords


def test_missing_keywords_list_capped_at_twenty():
    resume_text = "Contact: jane@example.com, phone 555-999-8888."
    jd_text = " ".join(f"keyword{i}" for i in range(40))

    report = ats_check("fake.pdf", jd_text, extract=lambda p: resume_text)

    assert len(report.missing_keywords) <= 20


def test_reading_order_scrambled_sections_flagged_not_ok():
    resume_text = """
    jane@example.com 555-111-2222
    Skills
    Python, Go
    Experience
    Backend engineer for five years.
    Education
    BS in CS.
    """
    # Canonical expected order is experience -> education -> skills; here
    # skills appears first, before experience/education, so it is scrambled.
    report = ats_check("fake.pdf", "python go experience", extract=lambda p: resume_text)

    assert report.reading_order_ok is False


def test_reading_order_ok_when_no_section_headers_present():
    resume_text = "jane@example.com 555-111-2222 A short bio with no headers."

    report = ats_check("fake.pdf", "python", extract=lambda p: resume_text)

    assert report.reading_order_ok is True


@pytest.mark.skipif(
    not shutil.which("lualatex") and not Path("/Library/TeX/texbin/lualatex").exists(),
    reason="no lualatex",
)
def test_live_ats_check_on_real_rendered_pdf(tmp_path):
    """Render a real PDF (Task 3 render_pdf, real lualatex) and run ats_check
    against it with the real pdftotext extractor (no injected extract)."""
    from job_dashboard.resume.render import render_pdf

    tex = r"""
\documentclass{article}
\begin{document}
John Doe

Email: john.doe@example.com \quad Phone: +1 555-123-4567

Experience

Built scalable Python services using Docker and Kubernetes for backend systems.

Education

BS Computer Science, State University.

Skills

Python, Docker, Kubernetes.
\end{document}
"""
    pdf_path = render_pdf(tex, tmp_path)
    assert pdf_path.exists()

    jd_text = "Looking for a backend engineer with strong Python and Docker experience."

    report = ats_check(pdf_path, jd_text)

    assert report.contact_ok is True
    assert "python" not in report.missing_keywords
    assert "docker" not in report.missing_keywords
    assert report.keyword_coverage > 0.0
