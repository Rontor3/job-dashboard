"""Perception: turn a page's raw form elements into the compact Form Model.

`to_form_model` is pure (unit-tested). `collect_raw`/`snapshot_form` are the
thin browser-bound collectors."""
from __future__ import annotations

from job_dashboard import paths

import json
import os
import re
import tempfile
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


_DATE_PART = {"day": "day", "dd": "day", "month": "month", "mm": "month", "year": "year", "yyyy": "year", "yy": "year"}
DATE_PARTS_PREFIX = "dateparts:"


def _part_of(r: dict):
    """'day' / 'month' / 'year' when the box says so: by its label, placeholder, first option ("Month") or name/id."""
    if r.get("kind") not in ("select", "text", "number", "combobox"):
        return None
    clean = lambda t: re.sub(r"[*:\s]", "", t or "").lower()
    for t in (r.get("label"), r.get("placeholder"), *(r.get("part_hint") or "").split()):
        if clean(t) in _DATE_PART:
            return _DATE_PART[clean(t)]
    return None


def merge_date_parts(raw: list[dict]) -> list[dict]:
    """Three neighbouring boxes labelled Day / Month / Year are ONE date question. Replace each such run with a single
    'date_parts' row whose ref carries the three part refs; the label is the question they share."""
    out, i = [], 0
    while i < len(raw):
        run = raw[i:i + 3]
        parts = [_part_of(r) for r in run]
        if len(run) == 3 and None not in parts and set(parts) == {"day", "month", "year"}:
            refs = {p: r["ref"] for p, r in zip(parts, run)}
            kinds = {p: r["kind"] for p, r in zip(parts, run)}
            label = next((r.get("group_label") for r in run if r.get("group_label")), "") or "Date"
            out.append({"ref": DATE_PARTS_PREFIX + json.dumps({"refs": refs, "kinds": kinds}), "kind": "date_parts",
                        "label": label, "required": any(r.get("required") for r in run), "options": [],
                        "input_type": "date", "description": "", "autocomplete": "", "placeholder": ""})
            i += 3
        else:
            out.append(raw[i]); i += 1
    return out


def to_form_model(raw: list[dict]) -> list[Field]:
    fields: list[Field] = []
    radio_groups: dict[str, dict] = {}

    for r in merge_date_parts(raw):
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
                {"labels": [], "required": False, "label": r["group"], "group_label": ""},
            )
            g["labels"].append(r["label"])
            g["required"] = g["required"] or bool(r.get("required"))
            if r.get("group_label") and not g["group_label"]:
                g["group_label"] = r["group_label"]
            continue
        fields.append(Field(
            ref=r["ref"], kind=kind, label=r["label"],
            required=bool(r.get("required")) or bool(re.search(r"^\s*\*|\*\s*$", r["label"] or "")), options=list(r.get("options", [])),
            group=r.get("group"),
            purpose=guess_purpose(r["label"], kind),
            description=r.get("description", ""),
            input_type=r.get("input_type", ""),
            autocomplete=r.get("autocomplete", ""),
            placeholder=r.get("placeholder", ""),
            max_length=int(r.get("max_length") or 0),
        ))

    for name, g in radio_groups.items():
        label = g.get("group_label") or name
        fields.append(Field(
            ref=f"group:{name}", kind="radio_group", label=label,
            required=g["required"], options=g["labels"], group=name,
            purpose=guess_purpose(label, "radio_group"),
        ))
    return fields


_INPUT_JS = r"""
() => {
  const out = [];
  // Query a selector across the light DOM AND every open shadow root
  // (LinkedIn / web-component ATS render their form fields inside shadow DOM,
  // which a plain document.querySelectorAll never reaches).
  // An id is a handle only when it names one element: Zoho gives several boxes id="inputId", and the first of them
  // is a hidden dial-code search — every value meant for Zip, City or State was typed there.
  const idRef = (el, cref) => {
    if (!el.id) return `[data-cref="${cref}"]`;
    const root = el.getRootNode();
    let n = 0;
    try { n = root.querySelectorAll(`#${CSS.escape(el.id)}`).length; } catch (e) { n = 2; }
    return n === 1 ? `#${CSS.escape(el.id)}` : `[data-cref="${cref}"]`;
  };
  const deepQuery = (sel) => {
    const res = [];
    const walk = (root) => {
      root.querySelectorAll(sel).forEach(e => res.push(e));
      // Only custom elements (tag names with '-') legitimately use shadow DOM for
      // form fields. Walking querySelectorAll('*') (all elements) to find shadow roots
      // is O(n) over the entire DOM and hangs on pages with large job-description blobs.
      root.querySelectorAll('*').forEach(e => {
        if (e.shadowRoot && e.tagName && e.tagName.includes('-')) walk(e.shadowRoot);
      });
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
    return v.split(/\s+/).map(id => {
      const n = byId(root, id);
      return n ? (n.textContent || '').trim().slice(0, 200) : '';
    }).join(' ').replace(/\s+/g, ' ').trim();
  };
  // Accessible NAME in the W3C accname priority order — this is what a screen
  // reader announces. Priority is the fix: aria-labelledby and aria-label come
  // BEFORE native <label>, and placeholder is a genuine last resort (so a React
  // combobox no longer reports "Select..."). Sibling/container text is kept only
  // as a fallback for forms with no formal association at all (e.g. Greenhouse).
  // A component wrapper that carries its field's question as an attribute and nothing the browser can see as a
  // label (Zoho Recruit: <crux-text-component cx-prop-label="First Name"> around a bare <input name="rec-form_…">).
  const OWNER_ATTRS = ['cx-prop-label', 'lt-prop-label', 'data-label'];
  const ownerLabel = (el) => {
    for (const a of OWNER_ATTRS) {                           // attribute order first: Zoho nests lt-prop-label="value"
      let p = el.parentElement;
      for (let i = 0; p && i < 10; i++, p = p.parentElement) {
        const v = (p.getAttribute(a) || '').trim();
        // a section's label (Zoho's consent block wraps two tick boxes, a remarks box and the consent box) names
        // none of them: only a wrapper of this one field (a phone's dial code + number counts as one) does
        const controls = p.querySelectorAll('input:not([type=hidden]),textarea,select').length;
        if (v && controls <= 3 && !/^(value|label|name|text|id)$/i.test(v)) return v.slice(0, 200);
      }
    }
    return '';
  };
  // A <label> element next to the wrapper that holds only this field, not linked to it (Zoho: "Please provide your
  // Consent *" after the tick box; "…enter your full name below as your signature…" before the remarks box). A tick
  // box's text follows it, anything else's precedes it.
  const nearLabel = (el) => {
    const isLabel = (n) => n && (n.tagName === 'LABEL' || /(^|[-_ ])label/i.test(n.className || ''));
    // a long statement ends with what it asks ("…Please enter your full name below as your signature…"): keep the end
    const text = (n) => { const t = (n.textContent || '').replace(/\s+/g, ' ').trim(); return t.length > 300 ? t.slice(-300) : t; };
    const tick = ['checkbox', 'radio'].includes((el.type || '').toLowerCase());
    let w = el;
    for (let i = 0; w && i < 6; i++, w = w.parentElement) {
      if (i && w.querySelectorAll('input:not([type=hidden]),textarea,select').length > 1) break;
      const order = tick ? [w.nextElementSibling, w.previousElementSibling] : [w.previousElementSibling, w.nextElementSibling];
      for (const n of order) if (isLabel(n) && !n.querySelector('input,textarea,select') && text(n)) return text(n);
    }
    return '';
  };
  const labelFor = (el) => {
    const root = el.getRootNode();
    const lb = idRefsText(el, 'aria-labelledby');            // 1
    if (lb) return lb;
    const al = (el.getAttribute('aria-label') || '').trim(); // 2
    if (al) return al;
    // a label's OWN text: a <label> wrapping a <select> also contains the option list, which is not the question
    const ownText = (l) => { const c = l.cloneNode(true); c.querySelectorAll('select,option,input,textarea,button,[role=listbox],[role=option]').forEach(x => x.remove()); return (c.textContent || '').trim().slice(0, 200); };
    if (el.id) {                                             // 3: <label for>
      const l = root.querySelector(`label[for="${el.id}"]`);
      if (l) { const t = ownText(l); if (t) return t; }
    }
    const wrap = el.closest('label');                        // 3: wrapping <label>
    if (wrap) { const t = ownText(wrap); if (t) return t; }
    const fs = el.closest('fieldset');                       // 3: fieldset legend
    if (fs) { const lg = fs.querySelector('legend'); if (lg) { const t = (lg.textContent || '').trim().slice(0, 200); if (t) return t; } }
    const title = (el.getAttribute('title') || '').trim();   // 4
    if (title) return title;
    const owned = ownerLabel(el);                            // component frameworks (Zoho's Lyte: cx-prop-label)
    if (owned) return owned;
    // ---- fallbacks below are NOT accname; only for forms with no association ----
    // Limit sibling walk to 3 and use textContent (no layout forcing) capped at
    // 200 chars — calling innerText on a large sibling (e.g. a job-description div)
    // forces full layout and can block the browser for minutes.
    let prev = el.previousElementSibling, sc = 0;
    while (prev && sc++ < 3) {
      const t = (prev.textContent || '').trim().slice(0, 200);
      if (t) return t;
      prev = prev.previousElementSibling;
    }
    const container = el.closest('div,section,fieldset,li');
    if (container) {
      const lbl = container.querySelector('label,legend,.label,[class*=label]');
      if (lbl) { const t = (lbl.textContent || '').trim().slice(0, 200); if (t) return t; }
    }
    const near = nearLabel(el);                              // a <label> beside the field's own wrapper
    if (near) return near;
    return (el.getAttribute('placeholder') || el.name || '').trim();   // 5: last resort
  };
  // Accessible DESCRIPTION — the helper text (aria-describedby). This is the piece
  // we used to drop; it carries hints like "type 'relocating'" that change what
  // a field means.
  const describedBy = (el) => idRefsText(el, 'aria-describedby');
  // textContent, but skipping aria-hidden subtrees — a screen reader (and the
  // accname algorithm) never announces them, yet plain textContent does. Custom
  // ARIA radio/checkbox widgets (Typeform, and similar React choice-button
  // libraries) render a decorative aria-hidden keyboard-shortcut badge right next
  // to the option text ("KeyA" + "0-1 year"); textContent glues them together
  // into "KeyA0-1 year", which then matches nothing.
  const visibleText = (el) => {
    if (!el) return '';
    let text = '';
    const walk = (node) => {
      if (node.nodeType === Node.TEXT_NODE) { text += node.textContent; return; }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      if (node.getAttribute('aria-hidden') === 'true') return;
      for (const child of node.childNodes) walk(child);
    };
    walk(el);
    return text.replace(/\s+/g, ' ').trim().slice(0, 200);
  };
  // For radio/checkbox groups the question heading is a sibling element of the
  // options container, not an ancestor of the individual input (so labelFor
  // returns the option text "Male" instead of the question "Gender"). Walk up
  // to 8 levels looking for a known ATS question-container class, then return
  // the first child text that isn't the options list itself.
  const groupLabel = (el) => {
    let node = el.parentElement;
    for (let i = 0; i < 8 && node; i++, node = node.parentElement) {
      const cls = (node.className || '');
      if (/\b(question|form[-_]?(group|row|item)|field[-_]?wrapper|application-question|card[-_]?body)\b/.test(cls)) {
        for (const ch of node.children) {
          if (/\b(field|option|choice|answer|radio|check|ul|list)\b/.test(ch.className || '')) continue;
          // Prefer a label-class descendant (avoids pulling in options that follow)
          const lbl = ch.querySelector && ch.querySelector('[class*=label],[class*=heading],legend,h1,h2,h3,h4,h5');
          const raw = lbl ? lbl.textContent : ch.textContent;
          const t = (raw || '').replace(/[✱*✶†]\s*$/, '').trim().slice(0, 200);
          if (t && t.length > 1) return t;
        }
      }
    }
    // Structural fallback: CSS-module ATSes (Workable etc.) use hashed class names
    // that don't match the known-class list above. Find the nearest container that
    // has BOTH text-only children AND radio/checkbox children — that's the question
    // block — and return the text-only part.
    let node2 = el.parentElement;
    for (let i = 0; i < 8 && node2; i++, node2 = node2.parentElement) {
      const kids = Array.from(node2.children);
      if (kids.length < 2) continue;
      const radioKids = kids.filter(k => k.querySelector('input[type=radio],input[type=checkbox]'));
      if (radioKids.length === 0) continue;
      const textKids = kids.filter(k => {
        if (k.querySelector('input[type=radio],input[type=checkbox]')) return false;
        const t = (k.textContent || '').trim();
        return t.length > 3 && t.length < 300;
      });
      if (textKids.length > 0) {
        const t = (textKids[0].textContent || '').replace(/[✱*✶†✳＊]\s*$/, '').replace(/^\s*[*✱]\s*/, '').trim().slice(0, 200);
        if (t && t.length > 3) return t;
      }
    }
    return '';
  };
  // Stamp a unique handle on every field so it's addressable even with no id and
  // no name (custom widgets share [name=""] otherwise). Prefer #id when present
  // (stable, readable); else use the stamped [data-cref="fN"].
  // A stamp is the element's for the life of the page, numbered from one page-wide counter, so it is never reused:
  // a decision made before a rescan (Zoho adds its consent block once the email is typed) still names its own box.
  // Restarting at f0 each scan gave two elements "f23"; wiping and renumbering moved Street from f4 to f5 between
  // deciding and typing, so its value went into another box.
  if (window.__crefN === undefined) window.__crefN = 0;
  const _now = new Set();                        // stamped in THIS scan
  const stamp = (el) => {
    let c = el.getAttribute('data-cref');
    if (!c) { c = 'f' + (window.__crefN++); el.setAttribute('data-cref', c); }
    _now.add(el);
    return c;
  };
  for (const el of deepQuery('input,select,textarea')) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || 'text').toLowerCase();
    if (type === 'hidden' || type === 'submit' || type === 'button') continue;
    // Skip inputs inside page chrome (header, nav, search bar) — they are site
    // navigation controls, not application form fields (Phenom/Mastercard has
    // a jobs-search bar in the header whose selects navigate the page if filled).
    if (el.closest('header, nav, [role="navigation"], [role="banner"], [role="search"]')) continue;
    // React-Select's validation stand-in (Greenhouse): an aria-hidden, untabbable text input next to the real
    // combobox. It's no field of its own; listed, it showed as a required "Select..." nobody could fill.
    if (tag === 'input' && ['text', ''].includes(type) && el.getAttribute('aria-hidden') === 'true'
        && el.getAttribute('tabindex') === '-1') continue;
    // Skip genuinely invisible fields (display:none, on the element or an
    // ancestor) — accessible combobox widgets (Workday) pair a visible trigger
    // button with an invisible shadow <input> carrying the same accessible
    // label; without this the shadow twin gets independently "filled" with a
    // resume/judgment value that has nothing to do with what's actually on
    // screen. getComputedStyle (not offsetParent, which needs layout to have
    // already run and can false-positive on a fast-loading iframe) is the check.
    const shown = (n) => !!n && (n.checkVisibility ? n.checkVisibility() : getComputedStyle(n).display !== 'none');
    // An upload widget hides its <input type=file> behind a styled "Browse" button (Zoho): the widget shows, so the
    // input is a real field.
    const uploadShown = () => { let p = el.parentElement; for (let i = 0; p && i < 4; i++, p = p.parentElement) if (shown(p) && p.getBoundingClientRect().height > 4) return true; return false; };
    if (!shown(el) && !(type === 'file' && uploadShown())) continue;
    const role = (el.getAttribute('role') || '').toLowerCase();
    const haspopup = (el.getAttribute('aria-haspopup') || '').toLowerCase();
    // Workday's own type-ahead multiselect (data-uxi-widget-type="selectinput")
    // has NO role/aria-haspopup/aria-controls linking it to its results list —
    // the only signal is this vendor attribute. It also needs typing (not just
    // a click) to reveal any options, unlike a plain click-to-open listbox.
    const uxiWidget = (el.getAttribute('data-uxi-widget-type') || '').toLowerCase();
    const isUxiSelect = uxiWidget.includes('select');
    let kind = tag === 'textarea' ? 'textarea'
             : tag === 'select' ? 'select'
             : isUxiSelect ? 'combobox'
             : ['email','tel','file','checkbox','radio'].includes(type) ? type
             : 'text';
    const options = tag === 'select'
      ? Array.from(el.options).map(o => o.text.trim())
          .filter(t => t && !/^(please select|select an option|select|choose|--|n\/a|none|select\.\.\.)$/i.test(t))
      : [];
    // A combobox is interacted with by clicking, not typing, so readOnly is
    // normal there and must NOT drop it as if disabled.
    const isCombo = role === 'combobox' || haspopup === 'listbox' || isUxiSelect;
    const cref = stamp(el);
    el.setAttribute('data-cref', cref);          // unique, id/name-independent handle
    // A read-only text box that opens a calendar: it cannot be typed into, so it is its own kind ('datepicker')
    // and is kept even though it is readonly. Signals are structural (date-ish name/class/placeholder/popup role).
    const dateish = /date|calendar|picker|dd.?mm|yyyy/i;
    const lab0 = labelFor(el);
    const isPicker = !!el.readOnly && !isCombo && ['text', ''].includes(type) && tag === 'input' &&
      (dateish.test((el.name || '') + ' ' + (el.id || '') + ' ' + (el.getAttribute('placeholder') || '') + ' ' + (el.className || '')) ||
       ['dialog', 'grid'].includes(haspopup) || /\bdate\b/i.test(lab0) || !!el.closest('[class*="datepicker" i], [class*="date-picker" i], [class*="calendar" i]'));
    if (isPicker) kind = 'datepicker';
    // One date split over day / month / year boxes: each part reports the question shared by the three
    const partWords = [lab0, el.getAttribute('placeholder'), el.name, el.id, tag === 'select' && el.options.length ? el.options[0].text : '']
      .map(t => (t || '').replace(/[*:\s]/g, ''));
    const isDatePart = partWords.some(t => /^(day|dd|month|mm|year|yyyy|yy)$/i.test(t));
    const dateGroup = () => {
      const fs = el.closest('fieldset');
      const lg = fs && fs.querySelector('legend');
      if (lg && lg.textContent.trim()) return lg.textContent.trim().slice(0, 200);
      return groupLabel(el);
    };
    // A radio whose name is the whole question, shared by every radio in its group (LinkedIn Easy Apply: aria-label
    // = question, an empty <label>, "Yes"/"No" in a sibling <p>): its option is the nearest text that is its own.
    const radioOption = () => {
      const peers = el.name ? [...document.getElementsByName(el.name)].filter(r => r !== el && r.type === 'radio') : [];
      if (!peers.length || !peers.every(r => labelFor(r) === labelFor(el))) return '';
      for (let a = el.parentElement, i = 0; a && i < 4; a = a.parentElement, i++) {
        if (a.querySelectorAll('input[type=radio]').length > 1) break;
        const t = (a.innerText || '').trim();
        if (t) return t.slice(0, 200);
      }
      return '';
    };
    out.push({
      ref: idRef(el, cref),
      kind, label: (type === 'radio' && el.value && labelFor(el).startsWith(el.value)) ? el.value
        : (type === 'radio' && radioOption()) || labelFor(el), description: describedBy(el), required: !!el.required || el.getAttribute('aria-required') === 'true' || !!el.closest('.mandatoryField'),
      options, group: (kind === 'radio') ? (el.name || null) : null,
      group_label: (kind === 'radio' || kind === 'checkbox')
        ? (groupLabel(el) || (type === 'radio' && radioOption() ? labelFor(el) : '')) : (isDatePart ? dateGroup() : ''),
      disabled: !!el.disabled || (!!el.readOnly && !isCombo && !isPicker && !['radio','checkbox'].includes(type)),   // React sets readonly on radios
      role, haspopup,
      input_type: type || '', autocomplete: (el.getAttribute('autocomplete') || '').toLowerCase(),
      placeholder: (el.getAttribute('placeholder') || '').trim().slice(0, 60),
      part_hint: [tag === 'select' && el.options.length ? el.options[0].text : '', el.name || '', el.id || ''].join(' ').trim().slice(0, 80),
      max_length: (typeof el.maxLength === 'number' && el.maxLength > 0 && el.maxLength < 100000) ? el.maxLength : 0,
    });
  }
  // A combobox that is not an <input>/<select>/<button>: a styled <div role="combobox"> that opens a listbox popup
  // (Indeed's single-select employer question). Same kind as the input comboboxes; the filler opens it and picks.
  for (const el of deepQuery('[role="combobox"]')) {
    const tag = el.tagName.toLowerCase();
    if (['input', 'select', 'textarea', 'button'].includes(tag) || _now.has(el)) continue;
    // a text box's own suggestion popup (Zoho's lyte-autocomplete wraps both): the box is the field, not a second one
    // (only a real wrapper with exactly one box: on a plain page the grandparent is <html> and holds every field)
    const widget = el.parentElement && el.parentElement.parentElement;
    if (widget && !['HTML', 'BODY', 'FORM'].includes(widget.tagName)
        && widget.querySelectorAll('input[data-cref]:not([type=hidden])').length === 1) continue;
    if (el.closest('header, nav, [role="navigation"], [role="banner"], [role="search"]')) continue;
    if (el.checkVisibility ? !el.checkVisibility() : getComputedStyle(el).display === 'none') continue;
    const cref = stamp(el);
    el.setAttribute('data-cref', cref);
    const lab = labelFor(el);
    const row = {
      ref: idRef(el, cref),
      kind: 'combobox', label: lab, description: describedBy(el),
      required: el.getAttribute('aria-required') === 'true' || /[*]\s*$|\(\*\)/.test(lab),
      options: [], group: null, group_label: '',
      disabled: el.getAttribute('aria-disabled') === 'true',
      role: 'combobox', haspopup: (el.getAttribute('aria-haspopup') || '').toLowerCase(),
      input_type: '', autocomplete: '', placeholder: '', part_hint: '',
    };
    // keep page order: before the first collected row whose element comes after this one in the document
    const at = out.findIndex(r => { try { const o = document.querySelector(r.ref); return !!o && !!(el.compareDocumentPosition(o) & 4); } catch (e) { return false; } });
    if (at >= 0) out.splice(at, 0, row); else out.push(row);
  }
  // Custom ARIA choice buttons: <button role="radio"> grouped under a
  // [role="radiogroup"] container (Typeform and similar React choice-button
  // widgets — no native <input type=radio> to key off, so the type=radio
  // grouping above never sees them). Same structural pattern, different
  // markup: group by the nearest radiogroup container, question text is its
  // preceding sibling (mirrors the native-radio group_label sibling walk).
  for (const el of deepQuery('[role="radio"]')) {
    if (el.closest('header, nav, [role="navigation"], [role="banner"], [role="search"]')) continue;
    const container = el.closest('[role="radiogroup"]') || el.parentElement;
    if (!container.hasAttribute('data-cref-group')) {
      container.setAttribute('data-cref-group', 'g' + (window.__crefN++));
    }
    const heading = container.previousElementSibling;
    const headingText = heading ? visibleText(heading) : '';
    // aria-required lies on some custom widgets (Typeform sets it "false" even
    // on a visually-required question) — a trailing asterisk in the question
    // heading is the fallback required signal, same convention groupLabel()
    // already strips elsewhere.
    const hasAsterisk = /[✱*✶†✳＊]\s*$/.test(headingText);
    const cref = stamp(el);
    el.setAttribute('data-cref', cref);
    out.push({
      ref: idRef(el, cref),
      kind: 'radio', label: visibleText(el),
      required: container.getAttribute('aria-required') === 'true' || hasAsterisk,
      options: [], group: container.getAttribute('data-cref-group'),
      group_label: headingText.replace(/[✱*✶†✳＊]\s*$/, ''),
      disabled: el.getAttribute('aria-disabled') === 'true' || !!el.disabled,
      role: 'radio', haspopup: '',
    });
  }
  // Advance controls (Next/Continue/Submit): buttons and link-buttons. Captured
  // as kind 'button' so the step engine can find them; the mapper skips them
  // (no fillable purpose, not required).
  for (const el of deepQuery(
        'button, a[href], input[type=submit], input[type=button], [role=button]')) {
    const elRole = (el.getAttribute('role') || '').toLowerCase();
    if (elRole === 'radio' || elRole === 'checkbox') continue;  // handled above
    if (el.checkVisibility ? !el.checkVisibility() : getComputedStyle(el).display === 'none') continue;   // invisible (self or ancestor) shadow/duplicate control
    let label = ((el.textContent || el.value || el.getAttribute('aria-label') || '')).trim().slice(0, 100);
    if (!label) continue;
    // A native-select stand-in (Workday Canvas Kit, etc.): a <button
    // aria-haspopup="listbox"> that opens a listbox elsewhere in the DOM.
    // Its visible text is just the current value/"Select One" — the real
    // field name is folded into aria-label as "<Name> <Value> [Required]".
    // Strip the value and trailing "Required" back out to recover it, and
    // fill it like any other fake dropdown: open + pick, not blind text.
    const popupHaspopup = (el.getAttribute('aria-haspopup') || '').toLowerCase();
    if (popupHaspopup === 'listbox') {
      const ariaLabel = (el.getAttribute('aria-label') || '').trim();
      const required = /\bRequired\b\s*$/i.test(ariaLabel);
      let name = ariaLabel;
      if (label) name = name.replace(label, '').trim();
      name = name.replace(/\bRequired\b\s*$/i, '').trim();
      if (name) {
        label = name;
      } else {
        // aria-label carried no field name at all (just "Select One Required")
        // — the real question is a sibling of the button inside a shared
        // <fieldset> (Workday groups "question text + Select One control"
        // together, with no separate accessible label tying the two).
        const fs = el.closest('fieldset');
        if (fs) {
          const legend = fs.querySelector('legend');
          let t = legend ? (legend.textContent || '')
                         : (fs.textContent || '').replace(label, '');
          t = t.replace(/[✱*✶†✳＊]\s*$/, '').trim().slice(0, 200);
          if (t) label = t;
        }
      }
      const cref = stamp(el);
      el.setAttribute('data-cref', cref);
      out.push({
        ref: idRef(el, cref),
        kind: 'combobox', label, required,
        options: [], group: null, disabled: !!el.disabled,
        role: (el.getAttribute('role') || '').toLowerCase(), haspopup: popupHaspopup,
      });
      continue;
    }
    out.push({
      ref: el.id ? `#${CSS.escape(el.id)}` : `button:${label}`,
      kind: 'button', label, required: false,
      options: [], group: null, disabled: !!el.disabled,
    });
  }
  return out;
}
"""


# --- Frame-qualified refs -------------------------------------------------
# The application form is often inside a cross-origin <iframe> (an embedded ATS).
# Page JavaScript can't cross into it, but Playwright can (page.frames). We scan
# every frame and tag a child frame's refs "fN@@<selector>" so the filler knows
# which frame to act in. Main-frame refs (frame 0) stay bare — full back-compat.
_FRAME_SEP = "@@"


def split_ref(ref):
    """(frame_index, selector). 'f2@@#id' -> (2, '#id'); '#id' -> (0, '#id')."""
    if isinstance(ref, str) and ref[:1] == "f" and _FRAME_SEP in ref:
        head, sel = ref.split(_FRAME_SEP, 1)
        try:
            return int(head[1:]), sel
        except ValueError:
            return 0, ref
    return 0, ref


def frame_target(page, ref):
    """The page or child frame a ref lives in, plus the bare selector. Frame
    order is stable within a step (collect and fill run back-to-back)."""
    idx, sel = split_ref(ref)
    if idx == 0:
        return page, sel
    frames = page.frames
    return (frames[idx] if idx < len(frames) else page), sel


def _box(page, ref):
    try:
        target, sel = frame_target(page, ref)
        el = target.query_selector(sel)
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
    path = shot_path or paths.tmp("career_vision_form.png")
    try:
        page.screenshot(path=path, full_page=True, timeout=10000)
    except Exception:
        return form
    info = [{"ref": f.ref, "kind": f.kind, "current_label": f.label,
             "options": list(f.options), "box": _box(page, f.ref)} for f in unl]
    try:
        labels = vision_fn(path, info) or {}
    except Exception:
        labels = {}
    return apply_vision_labels(form, labels)


# Which child frames to read. Reading the wrong one can hang (fr.evaluate() has no
# timeout and waits on a still-loading or cross-origin frame), but an allow-list of
# hiring providers misses every provider not on it, and a company's own embedded form.
# So: skip frames known NOT to be applications, skip hidden / tiny ones, give the rest a
# short load window, then keep a frame only if it holds real form fields.
ATS_FRAME_HOSTS = (            # trusted: read without the size / content checks
    "greenhouse.io", "ashbyhq.com", "recruitee.com",
    "workable.com", "lever.co",
    "talentrecruit.com", "darwinbox.in",
    "successfactors.com", "taleo.net", "icims.com",
    "jobvite.com", "smartrecruiters.com",
    "keka.com", "freshteam.com",
)
NON_APPLICATION_FRAME_HOSTS = (  # captcha, analytics, ads, chat / media widgets
    "recaptcha", "hcaptcha.com", "challenges.cloudflare.com", "turnstile", "arkoselabs.com", "funcaptcha",
    "geetest.com", "googletagmanager.com", "google-analytics.com", "doubleclick.net", "googlesyndication.com",
    "facebook.com/tr", "facebook.com/plugins", "connect.facebook.net", "hotjar.com", "intercom.io", "intercomcdn.com",
    "driftt.com", "drift.com", "zdassets.com", "zendesk.com", "zopim.com", "crisp.chat", "tawk.to",
    "youtube.com", "youtube-nocookie.com", "player.vimeo.com", "linkedin.com/talentwidget",
)
_MIN_FRAME_W, _MIN_FRAME_H = 200, 100       # a reCAPTCHA checkbox is ~300x78; trackers are 0-1px
_LOAD_WAIT_MS, _TRUSTED_LOAD_WAIT_MS = 1500, 8000
_FIELD_KINDS = {"text", "email", "tel", "number", "url", "textarea", "select", "combobox", "date", "password"}
_CAPTCHA_FIELD = re.compile(r"captcha|turnstile|g-recaptcha-response", re.I)


def is_denied_frame(url: str) -> bool:
    """Known not to be an application (captcha / analytics / ads / chat / media), or empty."""
    return not url or url == "about:blank" or any(h in url for h in NON_APPLICATION_FRAME_HOSTS)


def is_trusted_frame(url: str) -> bool:
    return any(h in (url or "") for h in ATS_FRAME_HOSTS)


def looks_like_application(rows: list[dict]) -> bool:
    """Real form fields: two labelled fields you type or pick into, or one plus a
    button (a first step that asks only for an email). Captcha response fields,
    unlabelled inputs and checkbox/radio-only frames (cookie banners) don't count."""
    fields = [r for r in rows if r.get("kind") in _FIELD_KINDS and (r.get("label") or "").strip()
              and not _CAPTCHA_FIELD.search(f"{r.get('ref') or ''} {r.get('label') or ''}")]
    has_button = any(r.get("kind") == "button" for r in rows)
    return len(fields) >= 2 or (len(fields) >= 1 and has_button)


def _frame_is_visible_and_sizeable(fr) -> bool:
    try:
        el = fr.frame_element()
        box = el.bounding_box()
        return bool(box) and el.is_visible() and box["width"] >= _MIN_FRAME_W and box["height"] >= _MIN_FRAME_H
    except Exception:
        return False                              # detached / not attached to a visible element


def collect_raw(page) -> list[dict]:
    """Scan the main frame AND the child frames that can hold an application (embedded
    ATS iframes). Child frames' refs are frame-qualified so the filler targets the right frame."""
    out = []
    frames = page.frames
    print(f"[perc] {len(frames)} frames", flush=True)
    for idx, fr in enumerate(frames):        # frames[0] is the main frame
        url = fr.url or ""
        print(f"[perc] frame {idx}: {url[:60]!r}", flush=True)
        trusted = False
        try:
            if idx > 0:
                if is_denied_frame(url):
                    continue                      # captcha / analytics / ads / chat: never an application
                trusted = is_trusted_frame(url)
                if not trusted and not _frame_is_visible_and_sizeable(fr):
                    continue                      # hidden, tracking pixel or widget-sized
                fr.wait_for_load_state("domcontentloaded", timeout=_TRUSTED_LOAD_WAIT_MS if trusted else _LOAD_WAIT_MS)
            rows = fr.evaluate(_INPUT_JS)
        except Exception:
            continue                              # detached / cross-origin / still loading / blocked
        if idx == 0:
            out.extend(rows)
        elif trusted or looks_like_application(rows):
            for r in rows:
                r["ref"] = f"f{idx}{_FRAME_SEP}{r['ref']}"
                out.append(r)
    return out


def _slow_scroll_pass(page, step_px: int = 400, delay_ms: int = 350) -> None:
    """Scroll top→bottom→top in small steps so lazy/virtualized fields
    render into the DOM before we snapshot. Abrupt full-page jumps skip
    intersection-observer triggers and miss fields that only exist on scroll."""
    from .clicks import wait
    try:
        total = page.evaluate("document.body.scrollHeight")
        page.evaluate("window.scrollTo(0, 0)")
        wait(page, 200)
        pos = 0
        while pos < total:
            pos = min(pos + step_px, total)
            page.evaluate("(p) => window.scrollTo(0, p)", pos)
            wait(page, delay_ms)
        page.evaluate("window.scrollTo(0, 0)")   # back to top before fill
        wait(page, 200)
    except Exception:
        pass   # non-scrollable page / framed page — proceed anyway


def snapshot_form(page, verify_shot: str | None = None, scroll: bool = True, shot: bool = True) -> list[Field]:
    """Scroll through the page to trigger all lazy-rendered fields, snapshot
    the DOM, then optionally save a screenshot for visual verification.
    The agent harness re-reads a page many times: it scrolls only the first time and takes no debug screenshot."""
    if scroll:
        _slow_scroll_pass(page)
    from .page_prep import suppress_noise
    fields = suppress_noise(to_form_model(collect_raw(page)))
    # Screenshot after snapshot so a human (or next run) can verify nothing
    # visible was missed. Saved to the data root's tmp/ by default; caller can override.
    if not shot:
        return fields
    path = verify_shot or paths.tmp("career_agent_perception.png")
    try:
        page.screenshot(path=path, full_page=True, timeout=5000)   # debug record: never wait 30s on a stuck frame
        print(f"[perc] snapshot: {len(fields)} fields — verify screenshot → {path}", flush=True)
    except Exception:
        print(f"[perc] snapshot: {len(fields)} fields", flush=True)
    return fields
