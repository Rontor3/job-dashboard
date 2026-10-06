"""One screenshot of a filled page: the whole page if it is a sane height, otherwise the page scrolled
top to bottom one viewport at a time (a 20000px full-page image is unreadable and often fails)."""
from __future__ import annotations

from pathlib import Path

MAX_FULL_H = 6000          # px; taller than this -> scrolled segments
MAX_PARTS = 6              # safety cap on segments


def capture_page(page, base: str, max_full: int = MAX_FULL_H, max_parts: int = MAX_PARTS) -> list[str]:
    """Write `<base>.png` (and `<base>_2.png`, ... for a long page). Returns the paths, [] on failure.
    Best-effort: a screenshot must never break an application."""
    try:
        for old in Path(base).parent.glob(f"{Path(base).name}_*.png"):
            old.unlink(missing_ok=True)                   # parts of an earlier, longer capture
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(300)
        height = page.evaluate("Math.max(document.documentElement.scrollHeight, "
                               "document.body ? document.body.scrollHeight : 0)") or 0   # unknown -> full-page shot
        view = page.evaluate("window.innerHeight") or 800
        if height <= max_full:
            path = f"{base}.png"
            page.screenshot(path=path, full_page=True, timeout=5000)
            return [path]
        paths, y = [], 0
        for i in range(max_parts):
            page.evaluate(f"window.scrollTo(0, {y})")
            page.wait_for_timeout(250)
            path = f"{base}.png" if i == 0 else f"{base}_{i + 1}.png"
            page.screenshot(path=path, full_page=False, timeout=5000)
            paths.append(path)
            y += int(view * 0.9)
            if y >= height - 5:
                break
        page.evaluate("window.scrollTo(0, 0)")
        return paths
    except Exception:
        return []
