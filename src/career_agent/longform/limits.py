"""A field's length limit: the HTML maxlength, else a '500 characters' / '200 words' hint in its label or help text."""
from __future__ import annotations

import re

_CHARS = re.compile(r"(\d{2,5})\s*(?:characters?|chars?)", re.I)
_WORDS = re.compile(r"(\d{1,4})\s*words?", re.I)


def field_limit(field) -> int | None:
    if field is None:
        return None
    if getattr(field, "max_length", 0) > 0:
        return field.max_length
    text = f"{getattr(field, 'label', '')} {getattr(field, 'description', '')}"
    if m := _CHARS.search(text):
        return int(m.group(1))
    if m := _WORDS.search(text):
        return int(m.group(1)) * 6          # ponytail: ~6 chars per word, rough
    return None
