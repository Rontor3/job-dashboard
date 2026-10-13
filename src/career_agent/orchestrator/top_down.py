"""Fill a form the way a person does: from the top, one blank after the other.

The answers come from several sources (question bank, rules, the judge) in whatever order they were found; the page
does not care how they were found, so they are applied in PAGE ORDER, one at a time. After each one the form is
checked for change: an answer often reveals more fields (Country -> State, "Yes" -> "please explain"). When it does,
the page is read again, the remaining answers are re-pointed at the new positions (React ids are positional and shift),
and the new fields are answered and slotted in at their place in the order, so the next blank is always the topmost."""
from __future__ import annotations

import dataclasses
import re

MAX_FIELDS = 150          # a form with more than this is not being filled, it is looping

_SIG_JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 2 && r.height > 2; };
  const els = Array.from(document.querySelectorAll('input,select,textarea,[role=combobox],[role=radiogroup]')).filter(vis);
  return els.length + '|' + els.map(e => (e.id || e.name || e.getAttribute('aria-label') || '').slice(0, 24)).join(',');
}"""


def field_keys(fields) -> dict:
    """ref -> a key that survives a re-read: (label, kind, n-th field with that label and kind)."""
    seen: dict = {}
    out = {}
    for f in fields:
        base = (re.sub(r"\s+", " ", (f.label or "").strip().lower()), f.kind)
        out[f.ref] = base + (seen.get(base, 0),)
        seen[base] = seen.get(base, 0) + 1
    return out


def _signature(page) -> str:
    try:
        return page.evaluate(_SIG_JS)
    except Exception:
        return ""


def _value(page, d):
    """The field's committed value after a fill, or None when it can't be read."""
    from ..browser.filler import read_back
    try:
        return read_back(page, [d]).get(d.ref)
    except Exception:
        return None


def _holds_value(page, d) -> bool:
    return bool(str(_value(page, d) or "").strip())


def _apply_one(deps, page, d) -> None:
    try:
        deps.fill(page, [d], revalidate=False)
    except TypeError:                               # a deps object without the keyword (tests, other backends)
        deps.fill(page, [d])


def fill_top_down(page, deps, fields, decisions, needs, ctx, *, answer_fn=None, skip_prefilled=False, settle_ms=250):
    """Apply `decisions` in page order, re-reading the form whenever it changes. Returns (applied, needs): the
    decisions that were applied, in the order they were applied, and the fields still needing a human."""
    from .sensitive import split_sensitive
    if answer_fn is None:
        from .answering import answer_fields as answer_fn

    cur = list(fields)
    keys = field_keys(cur)
    plan = {keys[d.ref]: d for d in decisions if d.ref in keys}
    orphans = [d for d in decisions if d.ref not in keys]            # a ref the read did not list: apply last
    seen = {keys[f.ref] for f in cur if f.kind != "button"}
    done, applied, needs = set(), [], list(needs)
    sig = _signature(page)

    for _ in range(MAX_FIELDS):
        order = [keys[f.ref] for f in cur if keys.get(f.ref) in plan and keys[f.ref] not in done]
        if not order:
            break
        k = order[0]
        d = plan[k]
        done.add(k)
        if skip_prefilled and d.kind != "textarea" and d.action in ("fill", "select", "combobox") and _holds_value(page, d):
            print(f"[fill] kept site's value: {d.label[:50]!r} = {str(_value(page, d))[:40]!r}", flush=True)
            continue          # the site already filled it (résumé parse); a long answer is ours, never the parser's: write it
        _apply_one(deps, page, d)
        try:
            page.wait_for_timeout(settle_ms)
        except Exception:
            pass
        after = _value(page, d) if d.action in ("fill", "select", "combobox") else None
        if after is not None and not str(after).strip():
            # The answer did not take (no dropdown option matched what was typed, the box rejected it): it is not
            # filled, whatever was attempted. The field goes to the human with its real label.
            f = next((f for f in cur if f.ref == d.ref), None)
            if f is not None:
                needs.append(f)
            print(f"[fill] did not take: {d.label[:50]!r} = {str(d.value)[:40]!r}", flush=True)
        else:
            applied.append(d)
        new_sig = _signature(page)
        if new_sig == sig:
            continue
        sig = new_sig
        try:
            try:
                cur = list(deps.snapshot(page, scroll=False))    # re-read in place: no scroll to the top and back
            except TypeError:                                      # a deps object without the keyword (tests)
                cur = list(deps.snapshot(page))
        except Exception:
            continue
        keys = field_keys(cur)
        by_key = {keys[f.ref]: f for f in cur}
        for k2 in list(plan):                                         # the same fields, at their new positions
            if k2 not in done and k2 in by_key:
                plan[k2] = dataclasses.replace(plan[k2], ref=by_key[k2].ref)
        fresh = [f for f in cur if f.kind != "button" and keys[f.ref] not in seen]
        if fresh:
            seen |= {keys[f.ref] for f in fresh}
            fresh, _blocked = split_sensitive(fresh)
            if fresh:
                more, more_needs = answer_fn(fresh, ctx)
                for d2 in more:
                    if d2.ref in keys:
                        plan[keys[d2.ref]] = d2
                needs += more_needs
                print(f"[fill] revealed {len(fresh)} new field(s): {[f.label[:30] for f in fresh]}", flush=True)

    for d in orphans:
        _apply_one(deps, page, d)
        applied.append(d)
    try:
        from ..browser.filler import revalidate_invalid
        revalidate_invalid(page)
    except Exception:
        pass
    return applied, needs
