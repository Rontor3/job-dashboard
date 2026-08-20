"""Resume segment library loader.

Reads a manifest (``segments.yaml``) describing reusable resume blocks and
the LaTeX text file backing each one, and returns them as :class:`Segment`
objects. Used by the resume-tailoring engine to assemble a CV from real,
pre-authored content blocks rather than generating new text.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# Default location of the real segment library shipped with this package.
SEGMENTS_DIR = Path(__file__).resolve().parent.parent / "resume_segments"


@dataclass
class Segment:
    id: str
    kind: str
    title: str
    tags: list[str]
    tex_path: Path
    text: str
    exclusive_group: str | None = None
    default: bool = True  # False = opt-in block, offered in an "add" picker, not loaded by default
    group: str | None = None      # company/employer an experience block belongs to (editor nesting)
    role_header: bool = False     # True = this block is a company's role/date header, not a sub-project
    section: str | None = None    # override the section heading this block renders under (else derived from kind)


def load_segments(root: Path | str = SEGMENTS_DIR) -> list[Segment]:
    """Load all segments described by ``root/segments.yaml``.

    Each manifest entry's ``tex`` file is read relative to ``root``. Raises
    ``FileNotFoundError`` naming the missing tex file if one is absent.
    """
    root = Path(root)
    manifest_path = root / "segments.yaml"
    manifest = yaml.safe_load(manifest_path.read_text()) or {}

    segments: list[Segment] = []
    for entry in manifest.get("segments", []):
        tex_path = root / entry["tex"]
        # Prefer a gitignored "<name>.local.tex" override (real personal content:
        # contact block, education) so the committed .tex can be a placeholder.
        local = tex_path.with_suffix(".local.tex")
        if local.exists():
            tex_path = local
        if not tex_path.exists():
            raise FileNotFoundError(f"Segment tex file not found: {tex_path}")
        text = tex_path.read_text()
        segments.append(
            Segment(
                id=entry["id"],
                kind=entry["kind"],
                title=entry["title"],
                tags=list(entry.get("tags", [])),
                tex_path=tex_path,
                text=text,
                exclusive_group=entry.get("exclusive_group"),
                default=entry.get("default", True),
                group=entry.get("group"),
                role_header=entry.get("role_header", False),
                section=entry.get("section"),
            )
        )
    return segments
