"""Date inputs that cannot simply be typed into.

  * a read-only box that opens a calendar popup  -> pick_calendar(): open it, step to the right month, click the day
  * one date split over Day / Month / Year boxes -> fill_date_parts(): set each part by what it is (select / text / combobox)

Both work from structural signals only (aria-label / title / data-date on the day cells, prev/next controls, month and
year selects), never a particular date-picker library. The value to enter is an ISO date or a written dd/mm/yyyy."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from types import SimpleNamespace

from .clicks import pace
from .perception import frame_target

_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december"]


def parse_date_value(value) -> date | None:
    """ISO first; then dd/mm/yyyy (day first: this is an Indian profile); then '4 Nov 2026' / 'November 4, 2026'."""
    s = str(value or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10]) if re.match(r"\d{4}-\d{2}-\d{2}", s) else _parse_loose(s)
    except ValueError:
        return None


def _parse_loose(s: str) -> date | None:
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return date(y + 2000 if y < 100 else y, mo, d)
    for fmt in ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# --- calendar popup ---------------------------------------------------------------------------------------------

_FIND_JS = r"""([Y, M, D]) => {
  const months = %MONTHS%;
  const full = months[M - 1], abbr = full.slice(0, 3);
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
                     return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && s.display !== 'none'; };
  document.querySelectorAll('[data-date-hit]').forEach(e => e.removeAttribute('data-date-hit'));
  const iso = Y + '-' + String(M).padStart(2, '0') + '-' + String(D).padStart(2, '0');
  const monRe = new RegExp('\\b(' + full + '|' + abbr + ')\\b', 'i');
  const dayRe = new RegExp('(^|[^0-9])0?' + D + '(st|nd|rd|th)?([^0-9]|$)');
  const yearRe = new RegExp('\\b' + Y + '\\b');
  const bad = e => e.disabled || e.getAttribute('aria-disabled') === 'true' || /disabled|outside|other-?month|unavailable/i.test(e.className || '');
  for (const e of document.querySelectorAll('[aria-label],[title],[data-date],[data-value],[datetime]')) {
    if (e.tagName === 'INPUT' || e.tagName === 'SELECT' || !vis(e) || bad(e)) continue;
    const attrs = ['aria-label', 'title', 'data-date', 'data-value', 'datetime'].map(a => e.getAttribute(a)).filter(Boolean).join(' | ');
    if (attrs.includes(iso) || (monRe.test(attrs) && dayRe.test(attrs) && yearRe.test(attrs))) {
      e.setAttribute('data-date-hit', '1'); return {found: true};
    }
  }
  // month / year <select>s inside the calendar: set them directly
  let used = false;
  for (const s of document.querySelectorAll('select')) {
    if (!vis(s)) continue;
    const txt = Array.from(s.options).map(o => o.text.trim().toLowerCase());
    let idx = -1;
    if (txt.includes('january') && txt.includes('december')) idx = txt.findIndex(t => t === full || t === abbr);
    else if (txt.some(t => /^\d{4}$/.test(t))) idx = txt.findIndex(t => t === String(Y));
    if (idx >= 0 && s.selectedIndex !== idx) {
      s.selectedIndex = idx; s.dispatchEvent(new Event('input', {bubbles: true})); s.dispatchEvent(new Event('change', {bubbles: true})); used = true;
    }
  }
  // which month is showing: "November 2026" in a header-ish element
  let view = null;
  const head = new RegExp('(' + months.join('|') + ')\\s+(\\d{4})', 'i');
  for (const e of document.querySelectorAll('[aria-live],[class*=header i],[class*=title i],[class*=caption i],[class*=label i],h1,h2,h3,h4,h5,h6,th,button,div,span')) {
    if (!vis(e) || e.children.length > 3) continue;
    const m = (e.textContent || '').trim().match(head);
    if (m && (e.textContent || '').trim().length < 40) { view = [months.indexOf(m[1].toLowerCase()) + 1, parseInt(m[2], 10)]; break; }
  }
  return {found: false, used, view};
}""".replace("%MONTHS%", json.dumps(_MONTHS))

_NAV_JS = r"""(dir) => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 2 && r.height > 2 && getComputedStyle(e).visibility !== 'hidden'; };
  const want = dir > 0 ? /next|forward|›|»|chevron-?right|arrow-?right|\bnext\b/i : /prev|back|‹|«|chevron-?left|arrow-?left/i;
  const never = /year|decade|century|disabled/i;
  for (const e of document.querySelectorAll('button,[role=button],a,[class*=next i],[class*=prev i],th')) {
    if (!vis(e) || e.disabled || e.getAttribute('aria-disabled') === 'true') continue;
    const t = [e.getAttribute('aria-label'), e.getAttribute('title'), e.textContent, e.className].filter(Boolean).join(' ');
    if (want.test(t) && !never.test(t)) { e.click(); return true; }
  }
  return false;
}"""

_TEXT_CELL_JS = r"""([D]) => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 2 && r.height > 2; };
  // the popup is the grid / calendar-ish box, or whatever holds the next/prev buttons
  const nav = Array.from(document.querySelectorAll('button,[role=button]')).find(e => vis(e) && /next|prev/i.test((e.getAttribute('aria-label') || '') + (e.className || '')));
  const boxes = Array.from(document.querySelectorAll('[role=grid], table, [class*=calendar i], [class*=datepicker i], [id*=cal i]'));
  if (nav && nav.parentElement) boxes.push(nav.parentElement, nav.parentElement.parentElement);
  for (const g of boxes) {
    if (!g) continue;
    if (!vis(g)) continue;
    for (const c of g.querySelectorAll('td, button, [role=gridcell], div, span')) {
      if (!vis(c) || c.children.length > 1 || (c.textContent || '').trim() !== String(D)) continue;
      if (c.disabled || /disabled|outside|other-?month|old|new|muted/i.test(c.className || '')) continue;
      c.click(); return true;
    }
  }
  return false;
}"""

_CONFIRM_JS = r"""() => {
  for (const b of document.querySelectorAll('button,[role=button]')) {
    const r = b.getBoundingClientRect();
    if (r.width > 2 && r.height > 2 && /^(ok|apply|done|set|confirm|select|save)$/i.test((b.textContent || '').trim())) { b.click(); return true; }
  }
  return false;
}"""


def pick_calendar(page, target, sel: str, d: date, max_steps: int = 40) -> bool:
    """Open the popup behind a read-only date box and click `d`. True if the box ends up with a value."""
    pace(page)
    try:
        target.click(sel, timeout=4000)
    except Exception:
        return False
    page.wait_for_timeout(500)
    steps = 0
    while steps < max_steps:
        try:
            r = target.evaluate(_FIND_JS, [d.year, d.month, d.day])
        except Exception:
            return False
        if r.get("found"):
            pace(page)
            try:
                target.locator("[data-date-hit]").first.click(timeout=3000)
            except Exception:
                return False
            break
        view = r.get("view")
        if r.get("used"):
            page.wait_for_timeout(250)
            steps += 1
            continue
        if view and tuple(view) == (d.month, d.year):
            # the right month is showing but no cell carries a readable date: click the day by its number
            if not target.evaluate(_TEXT_CELL_JS, [d.day]):
                return False
            break
        direction = -1 if view and (view[1], view[0]) > (d.year, d.month) else 1
        if not target.evaluate(_NAV_JS, direction):
            return False
        page.wait_for_timeout(200)
        steps += 1
    else:
        return False
    page.wait_for_timeout(300)
    try:
        target.evaluate(_CONFIRM_JS)                    # some pickers need OK / Apply after the day
    except Exception:
        pass
    page.wait_for_timeout(300)
    try:
        return bool((target.locator(sel).first.input_value() or "").strip())
    except Exception:
        return True


# --- separate day / month / year ---------------------------------------------------------------------------------

def _option_for(part: str, d: date, options: list[str]) -> str | None:
    want = {"day": [str(d.day), f"{d.day:02d}"], "year": [str(d.year), f"{d.year % 100:02d}"],
            "month": [str(d.month), f"{d.month:02d}", _MONTHS[d.month - 1], _MONTHS[d.month - 1][:3]]}[part]
    for o in options:
        t = o.strip().lower()
        if t in want:
            return o
    for o in options:                                   # "November (11)", "11 - Nov", "2026"
        t = o.strip().lower()
        if part == "month" and (re.search(r"\b" + _MONTHS[d.month - 1][:3], t) or re.search(r"\b0?%d\b" % d.month, t)):
            return o
        if part != "month" and re.search(r"\b0?%d\b" % (d.day if part == "day" else d.year), t):
            return o
    return None


def fill_date_parts(page, ref: str, d: date) -> bool:
    """`ref` is the 'dateparts:{...}' ref built by perception.merge_date_parts."""
    from .filler import _pick_combobox
    spec = json.loads(ref.split(":", 1)[1])
    ok = True
    for part, pref in spec["refs"].items():
        target, sel = frame_target(page, pref)
        kind = spec["kinds"].get(part, "text")
        text = {"day": f"{d.day:02d}", "month": f"{d.month:02d}", "year": str(d.year)}[part]
        try:
            if kind == "select":
                opts = target.locator(sel).locator("option").all_text_contents()
                opt = _option_for(part, d, opts)
                if opt is None:
                    ok = False
                    continue
                target.select_option(sel, label=opt, timeout=4000)
            elif kind == "combobox":
                opts_text = {"day": str(d.day), "month": _MONTHS[d.month - 1].capitalize(), "year": str(d.year)}[part]
                _pick_combobox(page, target, sel, SimpleNamespace(value=opts_text, label=part), None)
            else:
                target.fill(sel, text, timeout=4000)
        except Exception:
            ok = False
    return ok
