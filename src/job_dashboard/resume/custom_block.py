"""User block text -> LaTeX \\item lines matching resume_segments/*.tex.
Every user string is escaped so a stray % / & / $ can't break lualatex.
Never raises."""
from __future__ import annotations
import re

_ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}"}

_UNESCAPE = {v: k for k, v in _ESC.items()}


def escape_tex(s) -> str:
    out = []
    for ch in str(s or ""):
        out.append(_ESC.get(ch, ch))
    return "".join(out)


def _clean_bullets(bullets):
    return [str(b).strip() for b in (bullets or []) if b and str(b).strip()]


def block_to_tex(kind, title, bullets) -> str:
    """Return \\item lines for a block. experience: one item per bullet.
    project/skills: lead the first item with \\textbf{title}."""
    items = _clean_bullets(bullets)
    if not items:
        return ""
    k = (kind or "").lower()
    lead = escape_tex(title) if title else ""
    lines = []
    if k in ("project", "skills") and lead:
        first = escape_tex(items[0])
        if k == "skills":
            body = ", ".join(escape_tex(b) for b in items)
            return rf"\item \textbf{{{lead}}}: {body}"
        lines.append(rf"\item \textbf{{{lead}}}: {first}")
        rest = items[1:]
    else:
        rest = items
    for b in rest:
        lines.append(rf"\item {escape_tex(b)}")
    return "\n".join(lines)


def segment_bullets(text: str) -> list[str]:
    """Inverse of block_to_tex: extract bullets from LaTeX segment text.

    Splits on \\item, strips \\textbf{...}: or \\textbf{...} wrapper,
    unescapes LaTeX codes, collapses whitespace, drops empties.
    Never raises.
    """
    if not text:
        return []

    try:
        # Split on \item
        parts = str(text).split(r"\item")
        bullets = []

        for part in parts:
            # Strip leading/trailing whitespace
            part = part.strip()
            if not part:
                continue

            # Strip \textbf{...}: or \textbf{...} wrapper
            # Match \textbf{...}: first, then \textbf{...}
            match = re.match(r"^\\textbf\{([^}]*)\}:\s*(.*)", part)
            if match:
                # Keep both the title and the rest
                title = match.group(1).strip()
                rest = match.group(2).strip()
                part = f"{title}: {rest}" if rest else title
            else:
                match = re.match(r"^\\textbf\{([^}]*)\}\s*(.*)", part)
                if match:
                    title = match.group(1).strip()
                    rest = match.group(2).strip()
                    part = f"{title} {rest}" if rest else title

            # Unescape LaTeX codes
            # Order matters: process longer escapes first
            part = part.replace(r"\textbackslash{}", "\\")
            part = part.replace(r"\textasciitilde{}", "~")
            part = part.replace(r"\textasciicircum{}", "^")
            part = part.replace(r"\&", "&")
            part = part.replace(r"\%", "%")
            part = part.replace(r"\$", "$")
            part = part.replace(r"\#", "#")
            part = part.replace(r"\_", "_")
            part = part.replace(r"\{", "{")
            part = part.replace(r"\}", "}")

            # Collapse whitespace
            part = " ".join(part.split())

            # Skip if empty after processing
            if part:
                bullets.append(part)

        return bullets
    except Exception:
        # Never raise
        return []
