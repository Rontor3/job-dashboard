"""Read what is in a form right now, by question: {accessible name: value}. Used to compare what the agent filled with what
was actually submitted (you may have changed answers while the form waited for you). Reads only; never types or clicks."""
from __future__ import annotations

_JS = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 2 && r.height > 2; };
  const txt = id => { const n = document.getElementById(id); return n ? (n.innerText || n.textContent || '').trim() : ''; };
  const nameOf = e => {
    const lb = (e.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean).map(txt).join(' ').trim();
    if (lb) return lb;
    if (e.getAttribute('aria-label')) return e.getAttribute('aria-label').trim();
    if (e.labels && e.labels[0]) { const c = e.labels[0].cloneNode(true); c.querySelectorAll('select,option,input,textarea,button').forEach(x => x.remove()); const t = (c.textContent || '').trim(); if (t) return t; }
    return (e.getAttribute('placeholder') || e.name || '').trim();
  };
  const out = {};
  for (const e of document.querySelectorAll('input,select,textarea,[role=combobox]')) {
    if (!vis(e)) continue;
    const tag = e.tagName.toLowerCase(), type = (e.getAttribute('type') || 'text').toLowerCase();
    if (['hidden', 'submit', 'button', 'search', 'file', 'password'].includes(type)) continue;
    if (type === 'radio') {
      if (!e.checked) continue;
      const g = e.closest('[role=radiogroup],fieldset');
      const q = g ? ((g.querySelector('legend') || {}).innerText || nameOf(g)) : e.name;
      if (q) out[q.trim()] = (e.labels && e.labels[0] ? e.labels[0].innerText : e.value).trim();
      continue;
    }
    const name = nameOf(e);
    if (!name) continue;
    let v;
    if (type === 'checkbox') v = e.checked ? 'True' : 'False';
    else if (tag === 'select') v = e.selectedIndex >= 0 ? e.options[e.selectedIndex].text.trim() : '';
    else if (tag === 'input' || tag === 'textarea') v = e.value;
    else v = (e.innerText || '').trim();
    if (v && !/^(select( an option)?|choose\.*|--)$/i.test(v)) out[name] = v;
  }
  return out;
}"""


def read_form_values(page) -> dict:
    """{name: value} across the page and its frames (an embedded ATS form lives in a frame). {} if nothing readable."""
    out: dict = {}
    for fr in [page, *[f for f in getattr(page, "frames", []) if f is not getattr(page, "main_frame", None)]]:
        try:
            out.update(fr.evaluate(_JS) or {})
        except Exception:
            continue
    return out
