"""User block text -> LaTeX \\item lines matching resume_segments/*.tex.
Every user string is escaped so a stray % / & / $ can't break lualatex.
Never raises."""
from __future__ import annotations
import re

_ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}"}

_UNESCAPE = {v: k for k, v in _ESC.items()}

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def escape_tex(s) -> str:
    out = []
    for ch in str(s or ""):
        out.append(_ESC.get(ch, ch))
    return "".join(out)


def _tex_inline(s) -> str:
    """Escape LaTeX specials while converting ``**bold**`` markdown to
    ``\\textbf{...}``. Bullet bodies pass through here so the impact-styled
    ``**term**`` markup from regenerate — and the ``**label**`` a segment
    bullet carries — render as real bold in the PDF instead of literal
    asterisks. The ``\\textbf{}`` wrapper is emitted directly (not escaped);
    only the surrounding/inner text is escaped. Never raises."""
    s = str(s or "")
    out = []
    pos = 0
    for m in _BOLD_RE.finditer(s):
        out.append(escape_tex(s[pos:m.start()]))
        out.append(rf"\textbf{{{escape_tex(m.group(1))}}}")
        pos = m.end()
    out.append(escape_tex(s[pos:]))
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
        first = _tex_inline(items[0])
        if k == "skills":
            body = ", ".join(_tex_inline(b) for b in items)
            return rf"\item \textbf{{{lead}}}: {body}"
        lines.append(rf"\item \textbf{{{lead}}}: {first}")
        rest = items[1:]
    else:
        rest = items
    for b in rest:
        lines.append(rf"\item {_tex_inline(b)}")
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
                # Keep the label as **bold** markdown so it round-trips: the
                # editor renders it bold, and block_to_tex converts it back to
                # \textbf{} on an edit (instead of the manifest title being
                # prepended a second time — the double-heading bug).
                title = match.group(1).strip()
                rest = match.group(2).strip()
                part = f"**{title}**: {rest}" if rest else f"**{title}**"
            else:
                match = re.match(r"^\\textbf\{([^}]*)\}\s*(.*)", part)
                if match:
                    title = match.group(1).strip()
                    rest = match.group(2).strip()
                    part = f"**{title}** {rest}" if rest else f"**{title}**"

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
