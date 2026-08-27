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
  const labelFor = (el) => {
    if (el.id) {
      const l = document.querySelector(`label[for="${el.id}"]`);
      if (l) return l.innerText.trim();
    }
    const wrap = el.closest('label');
    if (wrap) return wrap.innerText.trim();
    const fs = el.closest('fieldset');
    if (fs) { const lg = fs.querySelector('legend'); if (lg) return lg.innerText.trim(); }
    return (el.getAttribute('aria-label') || el.name || '').trim();
  };
  for (const el of document.querySelectorAll('input,select,textarea')) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || 'text').toLowerCase();
    if (type === 'hidden' || type === 'submit' || type === 'button') continue;
    let kind = tag === 'textarea' ? 'textarea'
             : tag === 'select' ? 'select'
             : ['email','tel','file','checkbox','radio'].includes(type) ? type
             : 'text';
    const options = tag === 'select'
      ? Array.from(el.options).map(o => o.text.trim()).filter(Boolean) : [];
    out.push({
      ref: el.id ? `#${el.id}` : `[name="${el.name}"]`,
      kind, label: labelFor(el), required: !!el.required,
      options, group: (kind === 'radio') ? (el.name || null) : null,
      disabled: !!(el.disabled || el.readOnly),
    });
  }
  // Advance controls (Next/Continue/Submit): buttons and link-buttons. Captured
  // as kind 'button' so the step engine can find them; the mapper skips them
  // (no fillable purpose, not required).
  for (const el of document.querySelectorAll(
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
    return to_form_model(collect_raw(page))
