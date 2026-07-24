"""Resume fit-loop: keyword-aware overflow cutting.

Implements one-page overflow cutting that preserves keyword-rich content.
- rank_lines: score lines by JD keyword hits + uniqueness bonus
- fit_to_page: iteratively remove lowest-ranked lines until content fits
- FitResult: dataclass holding kept/cut line lists
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class FitResult:
    """Result of fitting lines to a page.

    Attributes:
        kept: lines retained, in original order
        cut: lines removed due to overflow
    """

    kept: list[str]
    cut: list[str]


def rank_lines(
    lines: list[str], jd_keywords: set[str]
) -> list[tuple[float, str]]:
    """Rank lines by JD keyword relevance.

    Score = count of JD keywords appearing in the line (case-insensitive)
            + small uniqueness bonus (1 if line appears once, 0.5 if duplicate)

    Args:
        lines: candidate lines to rank
        jd_keywords: set of keywords to count (case-insensitive)

    Returns:
        list of (score, line) tuples, sorted by score (ascending)
    """
    scored_lines: list[tuple[float, str]] = []

    # Count duplicates to calculate uniqueness bonus
    line_counts = {}
    for line in lines:
        line_counts[line] = line_counts.get(line, 0) + 1

    for line in lines:
        # Count keyword hits (case-insensitive)
        line_lower = line.lower()
        keyword_count = sum(
            1 for keyword in jd_keywords if keyword.lower() in line_lower
        )

        # Uniqueness bonus: 1.0 if unique, 0.5 if duplicated
        uniqueness_bonus = 1.0 if line_counts[line] == 1 else 0.5

        # Total score
        score = float(keyword_count) + uniqueness_bonus * 0.1

        scored_lines.append((score, line))

    # Sort by score (ascending) so lowest-ranked are first
    scored_lines.sort(key=lambda x: x[0])

    return scored_lines


def fit_to_page(
    lines: list[str],
    jd_keywords: set[str],
    overflows: Callable[[list[str]], bool],
) -> FitResult:
    """Fit lines to page by cutting lowest-ranked content.

    Iteratively removes the lowest-ranked line until the content no longer
    overflows. Preserved order of kept lines (not rank order).

    Args:
        lines: candidate lines to fit
        jd_keywords: keywords for ranking lines
        overflows: injected function that returns True if candidate_lines
                  don't fit on one page (in tests: fake based on length;
                  in prod: render to PDF and measure page count)

    Returns:
        FitResult with kept lines (in original order) and cut lines
    """
    # Start with all lines
    current = lines.copy()
    cut: list[str] = []

    # Loop while overflows and have lines to cut
    while overflows(current) and current:
        # Rank current lines and find the lowest-ranked
        ranked = rank_lines(current, jd_keywords)

        if not ranked:
            break

        lowest_score, lowest_line = ranked[0]

        # Remove lowest from current, add to cut
        current.remove(lowest_line)
        cut.append(lowest_line)

        # Log the cut
        logger.info(f"Resume fit: cut '{lowest_line}'")

    # Reconstruct kept in original line order
    kept = [line for line in lines if line in current]

    return FitResult(kept=kept, cut=cut)
