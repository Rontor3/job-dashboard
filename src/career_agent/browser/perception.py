"""Perception: turn a page's raw form elements into the compact Form Model.

`to_form_model` is pure (unit-tested). `collect_raw`/`snapshot_form` are the
thin browser-bound collectors."""
from __future__ import annotations

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
                {"labels": [], "required": False, "label": r["group"], "group_label": ""},
            )
            g["labels"].append(r["label"])
            g["required"] = g["required"] or bool(r.get("required"))
            if r.get("group_label") and not g["group_label"]:
                g["group_label"] = r["group_label"]
            continue
        fields.append(Field(
            ref=r["ref"], kind=kind, label=r["label"],
            required=bool(r.get("required")), options=list(r.get("options", [])),
            group=r.get("group"),
            purpose=guess_purpose(r["label"], kind),
            description=r.get("description", ""),
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
  const labelFor = (el) => {
    const root = el.getRootNode();
    const lb = idRefsText(el, 'aria-labelledby');            // 1
    if (lb) return lb;
    const al = (el.getAttribute('aria-label') || '').trim(); // 2
    if (al) return al;
    if (el.id) {                                             // 3: <label for>
      const l = root.querySelector(`label[for="${el.id}"]`);
      if (l) { const t = (l.textContent || '').trim().slice(0, 200); if (t) return t; }
    }
    const wrap = el.closest('label');                        // 3: wrapping <label>
    if (wrap) { const t = (wrap.textContent || '').trim().slice(0, 200); if (t) return t; }
    const fs = el.closest('fieldset');                       // 3: fieldset legend
    if (fs) { const lg = fs.querySelector('legend'); if (lg) { const t = (lg.textContent || '').trim().slice(0, 200); if (t) return t; } }
    const title = (el.getAttribute('title') || '').trim();   // 4
    if (title) return title;
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
    return (el.getAttribute('placeholder') || el.name || '').trim();   // 5: last resort
  };
  // Accessible DESCRIPTION — the helper text (aria-describedby). This is the piece
  // we used to drop; it carries hints like "type 'relocating'" that change what
  // a field means.
  const describedBy = (el) => idRefsText(el, 'aria-describedby');
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
  let _ci = 0;
  for (const el of deepQuery('input,select,textarea')) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || 'text').toLowerCase();
    if (type === 'hidden' || type === 'submit' || type === 'button') continue;
    // Skip inputs inside page chrome (header, nav, search bar) — they are site
    // navigation controls, not application form fields (Phenom/Mastercard has
    // a jobs-search bar in the header whose selects navigate the page if filled).
    if (el.closest('header, nav, [role="navigation"], [role="banner"], [role="search"]')) continue;
    let kind = tag === 'textarea' ? 'textarea'
             : tag === 'select' ? 'select'
             : ['email','tel','file','checkbox','radio'].includes(type) ? type
             : 'text';
    const options = tag === 'select'
      ? Array.from(el.options).map(o => o.text.trim())
          .filter(t => t && !/^(please select|select an option|select|choose|--|n\/a|none|select\.\.\.)$/i.test(t))
      : [];
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
      group_label: (kind === 'radio' || kind === 'checkbox') ? groupLabel(el) : '',
      disabled: !!el.disabled || (!!el.readOnly && !isCombo),
      role, haspopup,
    });
  }
  // Advance controls (Next/Continue/Submit): buttons and link-buttons. Captured
  // as kind 'button' so the step engine can find them; the mapper skips them
  // (no fillable purpose, not required).
  for (const el of deepQuery(
        'button, a[href], input[type=submit], input[type=button], [role=button]')) {
    const label = ((el.textContent || el.value || el.getAttribute('aria-label') || '')).trim().slice(0, 100);
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


# Child frames are scanned ONLY when they come from a known embedded ATS.
# Scanning any other frame (hcaptcha, GTM, analytics, LinkedIn widgets) can
# block indefinitely — fr.evaluate() has no timeout and will wait for a
# still-loading or cross-origin frame without throwing.
_ATS_FRAME_HOSTS = (
    "greenhouse.io", "ashbyhq.com", "recruitee.com",
    "workable.com", "lever.co",
    "talentrecruit.com", "darwinbox.in",
    "successfactors.com", "taleo.net", "icims.com",
    "jobvite.com", "smartrecruiters.com",
    "keka.com", "freshteam.com",
)


def collect_raw(page) -> list[dict]:
    """Scan the main frame AND every child frame (embedded ATS iframes). Child
    frames' refs are frame-qualified so the filler targets the right frame."""
    out = []
    frames = page.frames
    print(f"[perc] {len(frames)} frames", flush=True)
    for idx, fr in enumerate(frames):        # frames[0] is the main frame
        print(f"[perc] frame {idx}: {fr.url[:60]!r}", flush=True)
        try:
            if idx > 0:
                url = fr.url or ""
                if not any(h in url for h in _ATS_FRAME_HOSTS):
                    continue                      # not an ATS embed — skip to avoid blocking
            rows = fr.evaluate(_INPUT_JS)
        except Exception:
            continue                              # detached / cross-origin / blocked
        if idx == 0:
            out.extend(rows)
        else:
            for r in rows:
                r["ref"] = f"f{idx}{_FRAME_SEP}{r['ref']}"
                out.append(r)
    return out


def _slow_scroll_pass(page, step_px: int = 400, delay_ms: int = 350) -> None:
    """Scroll top→bottom→top in small steps so lazy/virtualized fields
    render into the DOM before we snapshot. Abrupt full-page jumps skip
    intersection-observer triggers and miss fields that only exist on scroll."""
    try:
        total = page.evaluate("document.body.scrollHeight")
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(200)
        pos = 0
        while pos < total:
            pos = min(pos + step_px, total)
            page.evaluate("(p) => window.scrollTo(0, p)", pos)
            page.wait_for_timeout(delay_ms)
        page.evaluate("window.scrollTo(0, 0)")   # back to top before fill
        page.wait_for_timeout(200)
    except Exception:
        pass   # non-scrollable page / framed page — proceed anyway


def snapshot_form(page, verify_shot: str | None = None) -> list[Field]:
    """Scroll through the page to trigger all lazy-rendered fields, snapshot
    the DOM, then optionally save a screenshot for visual verification."""
    _slow_scroll_pass(page)
    from .page_prep import suppress_noise
    fields = suppress_noise(to_form_model(collect_raw(page)))
    # Screenshot after snapshot so a human (or next run) can verify nothing
    # visible was missed. Saved to /tmp by default; caller can override.
    shot = verify_shot or os.path.join(tempfile.gettempdir(), "career_agent_perception.png")
    try:
        page.screenshot(path=shot, full_page=True)
        print(f"[perc] snapshot: {len(fields)} fields — verify screenshot → {shot}", flush=True)
    except Exception:
        print(f"[perc] snapshot: {len(fields)} fields", flush=True)
    return fields
