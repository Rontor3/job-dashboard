"""User block text -> LaTeX \\item lines matching resume_segments/*.tex.
Every user string is escaped so a stray % / & / $ can't break lualatex.
Never raises."""
from __future__ import annotations
import re

_ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}"}

_UNESCAPE = {v: k for k, v in _ESC.items()}

# Unicode punctuation that a T1/lmodern lualatex run renders as mojibake
# (e.g. "·" -> "ů", "—" spacing) — mapped to LaTeX-safe equivalents. Kept
# OUT of _ESC so the segment_bullets round-trip (_UNESCAPE) is unaffected.
_UNICODE = {
    "·": r"$\cdot$", "•": r"$\cdot$",
    "—": "---", "–": "--", "‑": "-", "−": "-",
    "’": "'", "‘": "'", "“": "``", "”": "''",
    "…": r"\ldots{}", " ": " ",
}

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def escape_tex(s) -> str:
    out = []
    for ch in str(s or ""):
        if ch in _ESC:
            out.append(_ESC[ch])
        elif ch in _UNICODE:
            out.append(_UNICODE[ch])
        else:
            out.append(ch)
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
    """Return LaTeX for a block.

    experience: a self-contained bold sub-heading (the title) followed by
    its OWN ``itemize`` of bullets — so several experience blocks stack as
    nested sub-projects under one ``\\section{Experience}`` (e.g. three
    sub-projects under a Tata AIG role), matching the source résumé.
    A titled experience block with no bullets renders as a heading only
    (used for a role/company line). project/skills: lead the first item
    with ``\\textbf{title}`` (unchanged)."""
    items = _clean_bullets(bullets)
    k = (kind or "").lower()
    lead = escape_tex(title) if title else ""

    if k == "experience":
        head = rf"\textbf{{{lead}}}" if lead else ""
        # Drop bullets that are ONLY a bold heading (e.g. a sub-project name
        # duplicated from the block title) — they render as redundant headings.
        if lead:
            items = [b for b in items if not re.fullmatch(r"\s*\*\*[^*]+\*\*\s*", b)]
        if not items:
            return head
        body = "\n".join(rf"\item {_tex_inline(b)}" for b in items)
        itemize = "\\begin{itemize}\n" + body + "\n\\end{itemize}"
        return f"{head}\n{itemize}" if head else itemize

    if not items:
        return ""
    lines = []
    if k in ("project", "skills") and lead:
        if k == "skills":
            body = ", ".join(_tex_inline(b) for b in items)
            return rf"\item \textbf{{{lead}}}: {body}"
        # A project bullet that already opens with a bold heading (**Title**) IS
        # the title line — don't prepend the block title again (avoids doubling).
        if re.match(r"\s*\*\*", items[0]):
            rest = items
        else:
            lines.append(rf"\item \textbf{{{lead}}}: {_tex_inline(items[0])}")
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
        # Convert EVERY \textbf{X} to **X** up front (not just a leading one),
        # so multi-heading segments (a role line + sub-project sub-headings)
        # display cleanly in the editor instead of leaking raw \textbf{...}.
        text = re.sub(r"\\textbf\{([^}]*)\}", r"**\1**", str(text))
        # Everything before the FIRST \item is layout/structure — a role/company
        # line and a section sub-heading — not an editable bullet. A segment with
        # no \item at all is a pure heading and yields no bullets. This keeps the
        # role line and sub-heading out of the block's bullet list (the block
        # title carries them), so they never render twice.
        if r"\item" not in text:
            return []
        parts = str(text).split(r"\item")[1:]
        bullets = []

        for part in parts:
            # Strip leading/trailing whitespace
            part = part.strip()
            if not part:
                continue

            # Strip residual LaTeX *layout* (not prose) so it never leaks into
            # the editor UI: environment delimiters (\begin/\end{itemize}),
            # \hfill, and a BARE \textasciitilde (e.g. "\textasciitilde500" —
            # the escaped "\textasciitilde{}" form is left for the unescape
            # pass below). Done before \textbf/unescape handling. Deliberately
            # narrow — only these known layout commands — so escaped user
            # specials (\{, \_, \& …) still round-trip untouched.
            part = re.sub(r"\\(?:begin|end)\{[^}]*\}", " ", part)
            part = part.replace(r"\hfill", " ")
            part = re.sub(r"\\textasciitilde(?!\{)", "~", part)
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

            # LaTeX dash ligatures -> real Unicode dashes for clean display.
            part = part.replace("---", "—").replace("--", "–")

            # Collapse whitespace
            part = " ".join(part.split())

            # Skip if empty after processing
            if part:
                bullets.append(part)

        return bullets
    except Exception:
        # Never raise
        return []
