"""Open the empty entry forms a résumé section hides behind an 'Add' button.

Workday's My Experience (Walmart, live 2026-10-30) shows Work Experience and Education as a heading and a bare 'Add'
button. Nothing is required, so the page saved with both empty and the review read 'No Response'. Each section is
told by its own name (the button's aria-label, else the heading above it); it gets one entry per item the profile
holds, and the entry fields that appear are filled by orchestrator/entry_fields like any other page."""
from __future__ import annotations

import re

_WORK = re.compile(r"\b(work|employment|professional) (experience|history)\b|^experience$", re.I)
_EDU = re.compile(r"\beducation\b|\bacademic\b", re.I)

# Every visible 'Add' / 'Add Another' button: its section name, and how many entry boxes that section already shows.
_JS = r"""() => {
  const HEAD = 'h1,h2,h3,h4,h5,h6,[role=heading]';     // not a legend: an open entry's 'From*' date group has one
  return [...document.querySelectorAll('button')].filter(b => b.offsetParent &&
      /^add(\s+another)?\b/i.test((b.innerText || b.getAttribute('aria-label') || '').trim())).map((b, i) => {
    b.setAttribute('data-ca-add', String(i));
    let box = b.parentElement;
    while (box && !box.querySelector(HEAD)) box = box.parentElement;
    const heads = box ? [...box.querySelectorAll(HEAD)].filter(h =>
        h.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) : [];
    const head = heads[heads.length - 1];
    const label = (b.getAttribute('aria-label') || '').replace(/^add(\s+another)?\s*/i, '').trim();
    const boxes = head ? [...box.querySelectorAll('input:not([type=hidden]),textarea,select')].filter(e =>
        (head.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING) &&
        (e.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)) : [];
    return {i, name: label || (head ? head.innerText.trim() : ''), boxes: boxes.length};
  });
}"""

# Every entry key on the page ('workExperience-351', 'education-368'): an open entry has its own 'Work Experience 2'
# heading, so a section's count must come from the whole page, not from the boxes under the nearest heading.
_KEYS_JS = r"""() => [...new Set([...document.querySelectorAll('input,textarea,select,button')]
    .map(e => ((e.id || '').match(/^([A-Za-z]+-\d+)--/) || [])[1]).filter(Boolean))]"""
_KEY_KIND = {"experiences": re.compile(r"work|experience|employ", re.I), "education": re.compile(r"educat|school", re.I)}


def _have(page, kind, boxes) -> int:
    keys = [k for k in page.evaluate(_KEYS_JS) if _KEY_KIND[kind].search(k.split("-")[0])]
    return len(keys) if keys else (1 if boxes else 0)


def _kind(name: str) -> str | None:
    if _EDU.search(name):
        return "education"
    if _WORK.search(name):
        return "experiences"
    return None


def open_entries(page, profile) -> int:
    """Click 'Add' in each empty-or-short Work Experience / Education section until it shows one entry per profile item.
    Returns the clicks made. Never raises: a page without such sections is simply left as it is."""
    if profile is None:
        return 0
    clicks, stuck = 0, set()
    try:
        for _ in range(8):                      # one click at a time; the page grows after each
            todo = None
            for s in page.evaluate(_JS):
                kind = _kind(s["name"])
                want = len(getattr(profile, kind, None) or []) if kind else 0
                if want and kind not in stuck and want > _have(page, kind, s["boxes"]):
                    todo = s
                    break
            if todo is None:
                break
            kind = _kind(todo["name"])
            before = _have(page, kind, todo["boxes"])
            page.locator(f'[data-ca-add="{todo["i"]}"]').first.click(timeout=5000)
            page.wait_for_timeout(1500)
            clicks += 1
            print(f"[entries] opened a {todo['name'][:30]!r} entry", flush=True)
            # by kind, not name: the section reads 'Work Experience 1' once an entry is open, '… 2' after the next
            boxes = max((s["boxes"] for s in page.evaluate(_JS) if _kind(s["name"]) == kind), default=0)
            if _have(page, kind, boxes) <= before:
                stuck.add(kind)                 # that click opened nothing: leave this section, go on to the next
    except Exception as e:
        print(f"[entries] could not open entries ({type(e).__name__})", flush=True)
    return clicks
