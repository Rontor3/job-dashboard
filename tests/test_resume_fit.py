"""Tests for src/job_dashboard/resume/fit.py.

Unit tests for keyword-aware fit-loop that cuts lowest-ranked lines
when content overflows a page constraint.
"""

from __future__ import annotations

import logging

import pytest

from job_dashboard.resume.fit import FitResult, fit_to_page, rank_lines


def test_rank_lines_scores_by_keyword_count():
    """rank_lines returns (score, line) tuples sorted by relevance."""
    lines = [
        "generic filler text",
        "Python skills mentioned",
        "Python and Java expertise",
    ]
    keywords = {"python", "java"}

    result = rank_lines(lines, keywords)

    assert len(result) == 3
    # All items are (score, line) tuples
    assert all(isinstance(r, tuple) and len(r) == 2 for r in result)
    # Highest score should be the line with both keywords
    best_score, best_line = result[-1]
    assert "Python and Java" in best_line
    assert best_score > result[0][0]  # Better than generic


def test_rank_lines_case_insensitive():
    """rank_lines counts keywords case-insensitively."""
    lines = [
        "PYTHON expert",
        "python engineer",
    ]
    keywords = {"python"}

    result = rank_lines(lines, keywords)

    # Both should have the same score since both have the keyword once
    assert result[0][0] == result[1][0]


def test_fit_to_page_cuts_lowest_ranked_lines_until_fits():
    """fit_to_page cuts lowest-ranked lines until overflows returns False."""
    lines = [
        "Keyword-rich line about Python and Java",
        "generic filler",
        "more generic",
        "another filler",
    ]
    keywords = {"python", "java"}

    # Fake overflows: True while more than 2 lines, False when <= 2
    def fake_overflows(candidate_lines: list[str]) -> bool:
        return len(candidate_lines) > 2

    result = fit_to_page(lines, keywords, fake_overflows)

    assert isinstance(result, FitResult)
    assert len(result.kept) <= 2
    assert any("Keyword-rich line" in line for line in result.kept)
    # Generic lines should be cut
    assert len(result.cut) >= 2
    assert any("generic" in line for line in result.cut)


def test_fit_to_page_preserves_kept_order():
    """Kept lines preserve original order, not rank-sorted order."""
    lines = [
        "First line generic",
        "Second line with keyword",
        "Third line generic",
        "Fourth line with keyword",
    ]
    keywords = {"keyword"}

    def never_overflows(candidate_lines: list[str]) -> bool:
        return False

    result = fit_to_page(lines, keywords, never_overflows)

    # Should keep all lines in original order
    assert result.kept == lines
    assert result.cut == []


def test_fit_to_page_overflows_always_false_cuts_nothing(caplog):
    """When overflows never returns True, no lines are cut."""
    lines = ["Line A", "Line B", "Line C"]
    keywords = {"rare"}

    def never_overflows(candidate_lines: list[str]) -> bool:
        return False

    result = fit_to_page(lines, keywords, never_overflows)

    assert result.kept == lines
    assert result.cut == []
    # No cuts, no logs needed


def test_fit_to_page_logs_each_cut_line(caplog):
    """Each cut line is logged."""
    lines = [
        "Keep this with keyword",
        "Cut generic",
        "Cut also generic",
    ]
    keywords = {"keyword"}

    def fake_overflows(candidate_lines: list[str]) -> bool:
        return len(candidate_lines) > 1

    with caplog.at_level(logging.INFO):
        result = fit_to_page(lines, keywords, fake_overflows)

    # Should have cut at least one line
    assert len(result.cut) > 0
    # Verify cuts were logged (check caplog records)
    assert len(caplog.records) > 0


def test_fit_to_page_returns_fit_result_dataclass():
    """fit_to_page returns a FitResult with kept and cut lists."""
    lines = ["one", "two", "three"]
    keywords = set()

    def never_overflows(candidate_lines: list[str]) -> bool:
        return False

    result = fit_to_page(lines, keywords, never_overflows)

    assert isinstance(result, FitResult)
    assert hasattr(result, "kept")
    assert hasattr(result, "cut")
    assert isinstance(result.kept, list)
    assert isinstance(result.cut, list)


def test_fit_to_page_stops_when_empty():
    """fit_to_page stops cutting when lines list becomes empty."""
    lines = ["only line"]
    keywords = {"never"}

    def always_overflows(candidate_lines: list[str]) -> bool:
        return True

    result = fit_to_page(lines, keywords, always_overflows)

    # Should cut the line and stop
    assert result.kept == []
    assert result.cut == ["only line"]


def test_rank_lines_uniqueness_bonus():
    """rank_lines gives small bonus for unique (non-duplicated) lines."""
    lines = [
        "Duplicate line",
        "Duplicate line",
        "Unique line with keyword",
    ]
    keywords = {"keyword"}

    result = rank_lines(lines, keywords)

    # Unique line with keyword should rank highest
    best_score, best_line = result[-1]
    assert "Unique line with keyword" in best_line


def test_fit_to_page_keyword_rich_survives_overflow_cutting():
    """Keyword-rich line should survive when overflows true for generics."""
    lines = [
        "Many generic lines",
        "Another generic",
        "Keyword-rich with python skills and java experience",
        "More generic content",
        "Final generic",
    ]
    keywords = {"python", "java", "skills", "experience"}

    # Fake overflows: true while more than 2 lines
    def fake_overflows(candidate_lines: list[str]) -> bool:
        return len(candidate_lines) > 2

    result = fit_to_page(lines, keywords, fake_overflows)

    # Keyword-rich line should be kept
    assert any("python" in line.lower() for line in result.kept)
    # Most generics should be cut
    assert len(result.cut) >= 2
