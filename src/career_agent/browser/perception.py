"""Perception: turn a page's raw form elements into the compact Form Model.

`to_form_model` is pure (unit-tested). `collect_raw`/`snapshot_form` are the
thin browser-bound collectors."""
from __future__ import annotations

from .form_model import Field, guess_purpose


def to_form_model(raw: list[dict]) -> list[Field]:
    fields: list[Field] = []
    radio_groups: dict[str, dict] = {}

    for r in raw:
        # Disabled / read-only inputs aren't part of the fillable form — a human
        # can't type in them either. Drop them so the mapper never targets one
        # (a strict fill on a disabled field blocks and crashes the run).
        if r.get("disabled"):
            continue
        kind = r["kind"]
        # A React "fake dropdown" renders as a plain <input> but announces
        # role=combobox / aria-haspopup=listbox. Fill it by open+pick, never
        # by blind text entry — so type it as combobox, not text.
        if kind == "text" and (r.get("role") == "combobox"
                               or r.get("haspopup") == "listbox"):
            kind = "combobox"
        if kind == "radio" and r.get("group"):
            g = radio_groups.setdefault(
                r["group"],
                {"labels": [], "required": False, "label": r["group"]},
            )
            g["labels"].append(r["label"])
            g["required"] = g["required"] or bool(r.get("required"))
            continue
        fields.append(Field(
            ref=r["ref"], kind=kind, label=r["label"],
            required=bool(r.get("required")), options=list(r.get("options", [])),
            group=r.get("group"),
            purpose=guess_purpose(r["label"], kind),
        ))

    for name, g in radio_groups.items():
        fields.append(Field(
            ref=f"group:{name}", kind="radio_group", label=name,
            required=g["required"], options=g["labels"], group=name,
            purpose=guess_purpose(name, "radio_group"),
        ))
    return fields


_INPUT_JS = r"""
() => {
  const out = [];
  // Query a selector across the light DOM AND every open shadow root
  // (LinkedIn / web-component ATS render their form fields inside shadow DOM,
  // which a plain document.querySelectorAll never reaches).
  const deepQuery = (sel) => {
    const res = [];
    const walk = (root) => {
      root.querySelectorAll(sel).forEach(e => res.push(e));
      root.querySelectorAll('*').forEach(e => { if (e.shadowRoot) walk(e.shadowRoot); });
    };
    walk(document);
    return res;
  };
  const byId = (root, id) => (root.getElementById ? root.getElementById(id)
                              : root.querySelector('#' + CSS.escape(id)));
  const labelFor = (el) => {
    const root = el.getRootNode();   // ShadowRoot or Document — scope lookups here
    if (el.id) {
      const l = root.querySelector(`label[for="${el.id}"]`);
      if (l) return l.innerText.trim();
    }
    const wrap = el.closest('label');
    if (wrap) return wrap.innerText.trim();
    const fs = el.closest('fieldset');
    if (fs) { const lg = fs.querySelector('legend'); if (lg) return lg.innerText.trim(); }
    const al = el.getAttribute('aria-label');
    if (al) return al.trim();
    // aria-labelledby -> concatenated text of referenced element(s)
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const t = lb.split(/\s+/).map(id => {
        const n = byId(root, id); return n ? n.innerText : '';
      }).join(' ').trim();
      if (t) return t;
    }
    // a label-like element just before the input (Greenhouse renders the
    // visible label as a separate sibling, not a <label for>)
    let prev = el.previousElementSibling;
    while (prev) {
      const t = (prev.innerText || '').trim();
      if (t) return t;
      prev = prev.previousElementSibling;
    }
    const container = el.closest('div,section,fieldset,li');
    if (container) {
      const lbl = container.querySelector('label,legend,.label,[class*=label]');
      if (lbl && (lbl.innerText || '').trim()) return lbl.innerText.trim();
    }
    return (el.name || el.getAttribute('placeholder') || '').trim();
  };
  for (const el of deepQuery('input,select,textarea')) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || 'text').toLowerCase();
    if (type === 'hidden' || type === 'submit' || type === 'button') continue;
    let kind = tag === 'textarea' ? 'textarea'
             : tag === 'select' ? 'select'
             : ['email','tel','file','checkbox','radio'].includes(type) ? type
             : 'text';
    const options = tag === 'select'
      ? Array.from(el.options).map(o => o.text.trim()).filter(Boolean) : [];
    const role = (el.getAttribute('role') || '').toLowerCase();
    const haspopup = (el.getAttribute('aria-haspopup') || '').toLowerCase();
    // A combobox is interacted with by clicking, not typing, so readOnly is
    // normal there and must NOT drop it as if disabled.
    const isCombo = role === 'combobox' || haspopup === 'listbox';
    out.push({
      ref: el.id ? `#${el.id}` : `[name="${el.name}"]`,
      kind, label: labelFor(el), required: !!el.required,
      options, group: (kind === 'radio') ? (el.name || null) : null,
      disabled: !!el.disabled || (!!el.readOnly && !isCombo),
      role, haspopup,
    });
  }
  // Advance controls (Next/Continue/Submit): buttons and link-buttons. Captured
  // as kind 'button' so the step engine can find them; the mapper skips them
  // (no fillable purpose, not required).
  for (const el of deepQuery(
        'button, a[href], input[type=submit], input[type=button], [role=button]')) {
    const label = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
    if (!label) continue;
    out.push({
      ref: el.id ? `#${el.id}` : `button:${label}`,
      kind: 'button', label, required: false,
      options: [], group: null, disabled: !!el.disabled,
    });
  }
  return out;
}
"""


def collect_raw(page) -> list[dict]:
    return page.evaluate(_INPUT_JS)


def snapshot_form(page) -> list[Field]:
    from .page_prep import suppress_noise
    return suppress_noise(to_form_model(collect_raw(page)))
