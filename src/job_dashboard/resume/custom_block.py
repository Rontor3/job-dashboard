"""User block text -> LaTeX \\item lines matching resume_segments/*.tex.
Every user string is escaped so a stray % / & / $ can't break lualatex.
Never raises."""
from __future__ import annotations

_ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}"}


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
