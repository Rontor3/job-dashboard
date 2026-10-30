"""A question that tells you what to type in the boxes under it.

Walmart (live 2026-10-30): "If “YES”, provide the information … below. If No, please enter ‘Not Applicable’ in the
fields below." The sentence sits past the 200-character label cut, and fields come back grouped by kind, not page
order, so the boxes under it were read as fresh questions and drafted stories. Here the page is walked in its own
order: each text box under such a question carries (word, question ref, that question's answer now)."""
from __future__ import annotations

from dataclasses import replace

_JS = r"""() => {
  const RE = /\bif (?:no|not)\b[^.]{0,40}?\b(?:enter|type|write|put)\s+[‘'"“]([^’'"”]{2,30})[’'"”]\s+in (?:the |all )?(?:fields?|boxes?) below/i;
  const els = [...document.querySelectorAll(
      'input:not([type=hidden]),textarea,select,button[aria-haspopup],[role=combobox]:not(input)')].filter(e => e.offsetParent);
  const out = {};
  let hint = null;
  for (const e of els) {
    const text = e.tagName === 'TEXTAREA' || (e.tagName === 'INPUT' && /^(text|email|tel|number|url|)$/i.test(e.type || ''));
    if (text) { if (hint && e.id) out['#' + e.id] = hint; continue; }
    const box = e.closest('[data-automation-id^="formField"],fieldset,[role=group],.form-group') || e.parentElement;
    const m = ((box && box.innerText) || '').match(RE);
    const now = e.tagName === 'SELECT' ? ((e.options[e.selectedIndex] || {}).text || '')
        : (e.type === 'radio' || e.type === 'checkbox') ? (box.querySelector('input:checked') || {}).value || ''
        : (e.innerText || e.value || '');
    hint = m ? [m[1], e.id ? '#' + e.id : '', now.trim()] : null;   // the next question ends the block
  }
  return out;
}"""


def mark_below(page, fields):
    """Fields with `below` set where the page puts an "If No, enter 'X' in the fields below" question above them."""
    try:
        hints = page.evaluate(_JS) or {}
    except Exception:
        return fields
    return [replace(f, below=tuple(hints[f.ref])) if f.ref in hints else f for f in fields]
