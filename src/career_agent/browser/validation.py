"""Read the site's own validation messages after a click and name the fields they belong to.

The agent used to trust its own fills and click Continue again and again while the site's red
"This field is required" text sat unread (MetLife's phone code, Koch's Education and "Current?",
Workday's Continue loops on MKS/Hitachi/Salesforce — live 2026-10-19). This module is the
read-back half of that fix; the refill half lives in the graph's advance node.

Pairing follows the same contract the snapshot does (perception._INPUT_JS + collect_raw): a
field's identity is `#id` (CSS-escaped) or the stamped `[data-cref]`, and child-frame refs are
frame-qualified `fN@@<selector>` in page.frames order.
"""

from __future__ import annotations

# Per-frame: pair each visible error to the field it describes.
#   1) aria-describedby — the one link the site draws itself between field and message.
#   2) error nodes ([role=alert], .error/.invalid classes...) — bind the visually-nearest input
#      (walk up ancestor by ancestor; the first level holding any field decides).
#   3) [aria-invalid=true] fields with no message at all — refill candidates without words.
# Returns [{ref, message}] in page order; message may be "" (case 3).
_PAIR_ERRORS_JS = r"""
() => {
  const norm = t => (t || '').replace(/\s+/g, ' ').trim();
  const vis = (e) => {
    try { return typeof e.checkVisibility === 'function' ? !!e.checkVisibility() : e.offsetParent !== null; }
    catch (err) { return false; }
  };
  const fields = [];
  const walk = (root, sel, acc) => {
    root.querySelectorAll(sel).forEach(e => acc.push(e));
    root.querySelectorAll('*').forEach(e => {
      if (e.shadowRoot && e.tagName && e.tagName.includes('-')) walk(e.shadowRoot, sel, acc);
    });
  };
  walk(document, 'input,select,textarea', fields);
  const errNodes = [];
  walk(document, '[role=alert],[aria-live=assertive],[id*="error" i],[class*="error" i],[class*="invalid" i]', errNodes);
  const refOf = (el) => {
    if (!el || el.id === undefined) return '';
    if (el.id) return '#' + CSS.escape(el.id);
    const c = (el.getAttribute('data-cref') || '');
    return c ? '[data-cref="' + c + '"]' : '';
  };
  const out = new Map();                     // ref -> message
  const add = (ref, msg) => {
    const m = norm(msg).slice(0, 220);
    if (!ref || !m || m.length < 3) return false;
    const cur = out.get(ref) || '';
    if (cur.includes(m) || m.includes(cur)) { out.set(ref, cur.length >= m.length ? cur : m); return true; }
    out.set(ref, (cur + ' ' + m).slice(0, 220));
    return true;
  };
  // 1) aria-describedby
  for (const el of fields) {
    const d = (el.getAttribute('aria-describedby') || '').trim();
    if (!d) continue;
    const root = el.getRootNode ? el.getRootNode() : document;
    const msg = d.split(/\s+/).filter(Boolean).map(id => {
      const n = root.getElementById ? root.getElementById(id) : null;
      return n ? (n.innerText || '') : '';
    }).join(' ');
    if (norm(msg)) add(refOf(el), msg);
  }
  // 2) error nodes -> visually nearest field
  for (const e of errNodes) {
    if (!vis(e)) continue;
    const t = norm(e.innerText || '');
    if (!t || t.length >= 250) continue;
    const eb = e.getBoundingClientRect();
    let anc = e.parentElement, lvl = 0;
    while (anc && lvl++ < 5) {
      let best = null, bestD = 1e12;
      for (const f of fields) {
        try {
          if (!anc.contains(f)) continue;
          const r = f.getBoundingClientRect();
          if (r.width < 2 || r.height < 2) continue;
          const d = Math.abs((r.top + r.height / 2) - (eb.top + eb.height / 2))
                  + Math.abs(r.left - eb.left) * 0.4;
          if (d < bestD) { bestD = d; best = f; }
        } catch (err) {}
      }
      if (best && add(refOf(best), t)) break;
      anc = anc.parentElement;
    }
  }
  // 3) silent invalids: an aria-invalid field with no message is still a refill target
  const list = [...out.entries()].map(([ref, message]) => ({ref, message}));
  const touched = new Set(list.map(x => x.ref));
  for (const el of fields) {
    if (el.getAttribute && el.getAttribute('aria-invalid') === 'true' && vis(el)) {
      const ref = refOf(el);
      if (ref && !touched.has(ref)) list.push({ref, message: ''});
    }
  }
  return list.slice(0, 12);
}
"""

# A stepper/progress indicator moving is proof a step advanced even when every field
# label stayed the same (Workday and Avature wizards live inside one frame).
_PROGRESS_JS = """() => {
  const s = [];
  for (const el of document.querySelectorAll('[role=progressbar],[aria-current="step"]')) {
    try { if (!el.checkVisibility()) continue; } catch (e) { continue; }
    const t = (el.getAttribute('aria-label') || el.innerText || '').replace(/\\s+/g, ' ').trim();
    const now = el.getAttribute('aria-valuenow') || '';
    const one = (t + (now ? '@' + now : '')).slice(0, 60);
    if (one) s.push(one);
  }
  return s.join('|').slice(0, 480);
}"""


def progress_signature(page) -> str:
    """Where the progress indicator stands, as a string for screen_signature."""
    try:
        return page.evaluate(_PROGRESS_JS) or ""
    except Exception:
        return ""


def read_errors(page, limit: int = 12) -> list[dict]:
    """The site's visible field errors, pairs of {ref, message} pointing at this page's fields.
    [] when there are none or the page could not be read. Child-frame errors come back
    frame-qualified like collect_raw's refs."""
    try:
        frames = page.frames
    except Exception:
        return []                        # a stub page object in tests / a crashed tab
    from .perception import (_frame_is_visible_and_sizeable, is_denied_frame,
                             is_trusted_frame)
    errs: list[dict] = []
    for idx, fr in enumerate(frames):
        try:
            if idx > 0:
                url = fr.url or ""
                if is_denied_frame(url):
                    continue
                if not is_trusted_frame(url) and not _frame_is_visible_and_sizeable(fr):
                    continue
            rows = fr.evaluate(_PAIR_ERRORS_JS)
        except Exception:
            continue
        for r in rows or []:
            ref = r.get("ref") or ""
            if idx > 0 and ref:
                ref = f"f{idx}@@{ref}"
            errs.append({"ref": ref, "message": (r.get("message") or "")})
    seen, out = set(), []
    for e in errs:
        k = (e["ref"], e["message"])
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    return out[:limit]


def failing_fields(errors, form):
    """Pair the site's messages with this screen's Fields, by ref. Returns (fields, banners):
    `fields` — the ones the site rejected, each carrying its message in .description prefixed
    "Site says:", `banners` — messages with no field to point at (a dead-end / error page)."""
    import dataclasses as dc
    by_ref = {f.ref: f for f in form}
    fields, banners, seen = [], [], set()
    for e in errors or []:
        f = by_ref.get(e.get("ref") or "")
        if f is None or f.kind in ("button", "file", "datepicker"):
            if not e.get("ref") and e.get("message"):
                banners.append(e["message"])
            continue
        if f.ref in seen:
            continue
        seen.add(f.ref)
        desc = (f.description or "").strip()
        msg = (e.get("message") or "").strip()
        new_desc = (f"{desc} | Site says: {msg}" if (desc and msg)
                    else (f"Site says: {msg}" if msg else desc))
        fields.append(dc.replace(f, description=new_desc))
    return fields, banners


def ref_key(sig) -> str:
    """A stable, serialisable key for a screen_signature tuple (one refill round per screen)."""
    try:
        path, labels, prog = sig[0], sorted(set(sig[1])), sig[2] if len(sig) > 2 else ""
    except Exception:
        return repr(sig)
    import hashlib
    h = hashlib.sha1("|".join(labels).encode()).hexdigest()[:10]
    return f"{path}|{h}|{prog}"
