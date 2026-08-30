"""Perception: turn a page's raw form elements into the compact Form Model.

`to_form_model` is pure (unit-tested). `collect_raw`/`snapshot_form` are the
thin browser-bound collectors."""
from __future__ import annotations

import re
from dataclasses import replace

from .form_model import Field, guess_purpose

# A field the DOM couldn't label: empty, a placeholder-only value, or a
# checkbox/radio whose only text is the option itself (the question lives in a
# separate heading the accname computation can't reach). These are the vision
# fallback's job — no DOM extractor reaches a label that isn't there.
_PLACEHOLDER_LABEL = re.compile(
    r"^(select|start typing|pick( a)? date|choose|search|type here|"
    r"dd/mm|mm/dd|please select|--)\b|^\.\.\.|\.\.\.$", re.I)
_OPTION_ONLY = {"yes", "no", "n/a", "na", "true", "false", "-"}


def is_unlabeled(field) -> bool:
    lab = (field.label or "").strip()
    if not lab:
        return True
    if _PLACEHOLDER_LABEL.search(lab):
        return True
    if field.kind in ("checkbox", "radio", "radio_group") and lab.lower() in _OPTION_ONLY:
        return True
    return False


def apply_vision_labels(form, labels: dict):
    """Replace the labels of unlabeled fields with what vision read, and re-guess
    their purpose from the new label. `labels` maps ref -> the real question."""
    out = []
    for f in form:
        new = labels.get(f.ref)
        if new and is_unlabeled(f):
            out.append(replace(f, label=new, purpose=guess_purpose(new, f.kind)))
        else:
            out.append(f)
    return out


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
            description=r.get("description", ""),
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
  // Resolve id-references to their concatenated text (aria-labelledby/describedby).
  const idRefsText = (el, attr) => {
    const root = el.getRootNode();
    const v = el.getAttribute(attr);
    if (!v) return '';
    return v.split(/\s+/).map(id => { const n = byId(root, id); return n ? n.innerText : ''; })
            .join(' ').replace(/\s+/g, ' ').trim();
  };
  // Accessible NAME in the W3C accname priority order — this is what a screen
  // reader announces. Priority is the fix: aria-labelledby and aria-label come
  // BEFORE native <label>, and placeholder is a genuine last resort (so a React
  // combobox no longer reports "Select..."). Sibling/container text is kept only
  // as a fallback for forms with no formal association at all (e.g. Greenhouse).
  const labelFor = (el) => {
    const root = el.getRootNode();
    const lb = idRefsText(el, 'aria-labelledby');            // 1
    if (lb) return lb;
    const al = (el.getAttribute('aria-label') || '').trim(); // 2
    if (al) return al;
    if (el.id) {                                             // 3: <label for>
      const l = root.querySelector(`label[for="${el.id}"]`);
      if (l && l.innerText.trim()) return l.innerText.trim();
    }
    const wrap = el.closest('label');                        // 3: wrapping <label>
    if (wrap && wrap.innerText.trim()) return wrap.innerText.trim();
    const fs = el.closest('fieldset');                       // 3: fieldset legend
    if (fs) { const lg = fs.querySelector('legend'); if (lg && lg.innerText.trim()) return lg.innerText.trim(); }
    const title = (el.getAttribute('title') || '').trim();   // 4
    if (title) return title;
    // ---- fallbacks below are NOT accname; only for forms with no association ----
    let prev = el.previousElementSibling;
    while (prev) { const t = (prev.innerText || '').trim(); if (t) return t; prev = prev.previousElementSibling; }
    const container = el.closest('div,section,fieldset,li');
    if (container) {
      const lbl = container.querySelector('label,legend,.label,[class*=label]');
      if (lbl && (lbl.innerText || '').trim()) return lbl.innerText.trim();
    }
    return (el.getAttribute('placeholder') || el.name || '').trim();   // 5: last resort
  };
  // Accessible DESCRIPTION — the helper text (aria-describedby). This is the piece
  // we used to drop; it carries hints like "type 'relocating'" that change what
  // a field means.
  const describedBy = (el) => idRefsText(el, 'aria-describedby');
  // Stamp a unique handle on every field so it's addressable even with no id and
  // no name (custom widgets share [name=""] otherwise). Prefer #id when present
  // (stable, readable); else use the stamped [data-cref="fN"].
  let _ci = 0;
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
    const cref = 'f' + (_ci++);
    el.setAttribute('data-cref', cref);          // unique, id/name-independent handle
    out.push({
      ref: el.id ? `#${el.id}` : `[data-cref="${cref}"]`,
      kind, label: labelFor(el), description: describedBy(el), required: !!el.required,
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


def _box(page, ref):
    try:
        el = page.query_selector(ref)
        return el.bounding_box() if el else None
    except Exception:
        return None


def enrich_with_vision(page, form, vision_fn, shot_path=None):
    """For fields the DOM couldn't label, screenshot the page + collect the
    unlabeled fields' boxes, and ask `vision_fn` to read the real question from
    the picture. vision_fn(shot_path, [{ref,kind,current_label,options,box}])
    -> {ref: question}. No unlabeled fields or no vision_fn -> form unchanged."""
    if vision_fn is None:
        return form
    unl = [f for f in form if is_unlabeled(f)]
    if not unl:
        return form
    import os, tempfile
    path = shot_path or os.path.join(tempfile.gettempdir(), "career_vision_form.png")
    try:
        page.screenshot(path=path, full_page=True)
    except Exception:
        return form
    info = [{"ref": f.ref, "kind": f.kind, "current_label": f.label,
             "options": list(f.options), "box": _box(page, f.ref)} for f in unl]
    try:
        labels = vision_fn(path, info) or {}
    except Exception:
        labels = {}
    return apply_vision_labels(form, labels)


def collect_raw(page) -> list[dict]:
    return page.evaluate(_INPUT_JS)


def snapshot_form(page) -> list[Field]:
    from .page_prep import suppress_noise
    return suppress_noise(to_form_model(collect_raw(page)))
