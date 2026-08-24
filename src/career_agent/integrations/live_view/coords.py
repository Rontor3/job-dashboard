"""Map a normalized viewer pointer (0..1) to page pixels. Pure."""
from __future__ import annotations


def norm_to_px(nx: float, ny: float, width: int, height: int) -> tuple[int, int]:
    nx = min(1.0, max(0.0, nx))
    ny = min(1.0, max(0.0, ny))
    return (round(nx * width), round(ny * height))
