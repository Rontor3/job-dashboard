"""Shape a fill value to what the box accepts, right before it is typed.

  * a numerals-only box (type=number, a digits pattern, a "numerals only" hint) takes a plain number:
    '35 LPA' -> 3500000, '12 lakh' -> 1200000, '1.2 Cr' -> 12000000, '₹35,00,000' -> 3500000, '$120k' -> 120000
  * a month box takes 'YYYY-MM', a date box 'YYYY-MM-DD' (a month-only value gets day 01)

Anything else is returned exactly as it was: a text box keeps its answer. A value that does not parse is left alone,
so the box rejects it and the field goes to the human as before."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .date_widgets import parse_date_value

_NUMERALS_HINT = re.compile(r"numerals?\s+only|numbers?\s+only|digits?\s+only|only\s+(?:numerals?|numbers?|digits?)", re.I)
_DIGITS_PATTERN = re.compile(r"\^?(\[0-9\]|\\d)")          # a pattern that starts with a digit class: [0-9]+, \d{4}
_MONEY = re.compile(
    r"^\s*(?:₹|rs\.?|inr|\$|usd)?\s*(?P<num>\d[\d,]*(?:\.\d+)?|\.\d+)\s*"
    r"(?P<unit>lpa|lakhs?|lacs?|crores?|cr|k)?\s*(?:p\.?a\.?|per\s+annum)?\s*$", re.I)
_UNIT = {"k": 1_000, "lpa": 100_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
         "cr": 10_000_000, "crore": 10_000_000, "crores": 10_000_000}
_MONTH_ABBR = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_SHAPE_JS = r"""e => {
  const text = id => { const n = document.getElementById(id); return n ? (n.innerText || n.textContent || '') : ''; };
  const described = (e.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean).map(text).join(' ');
  // a hint printed beside the box with no aria link (Avature 'Enter numerals only', live Koch 2026-10-18): the text of
  // the smallest ancestor that holds this box alone
  let box = e.parentElement, near = '';
  for (let i = 0; box && i < 3; i++, box = box.parentElement) {
    if (box.querySelectorAll('input,select,textarea').length > 1) break;
    near = (box.innerText || '').slice(0, 200);
  }
  return {type: (e.getAttribute('type') || '').toLowerCase(), placeholder: e.getAttribute('placeholder') || '',
          pattern: e.getAttribute('pattern') || '', hint: described + ' ' + (e.getAttribute('title') || '') + ' ' + near};
}"""


def read_shape(target, sel) -> dict:
    """The box's own shape: its type, placeholder, pattern and described-by / title text. {} when unreadable."""
    try:
        return target.locator(sel).first.evaluate(_SHAPE_JS, timeout=4000) or {}
    except Exception:
        return {}


def _numerals_only(shape: dict) -> bool:
    return ((shape.get("type") or "") == "number"
            or bool(_DIGITS_PATTERN.search(shape.get("pattern") or ""))
            or bool(_NUMERALS_HINT.search(f"{shape.get('placeholder') or ''} {shape.get('hint') or ''}")))


def _plain_number(s: str) -> str | None:
    m = _MONEY.match(s)
    if not m:
        return None
    digits = m.group("num").replace(",", "")
    unit = (m.group("unit") or "").lower()
    if not unit:
        return digits
    try:
        n = Decimal(digits) * _UNIT[unit]
    except InvalidOperation:
        return None
    return str(int(n)) if n == n.to_integral_value() else format(n.normalize(), "f")


def _month_year(s: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"\s*([A-Za-z]{3,9})\.?,?\s+(\d{4})\s*", s)
    if m and m.group(1)[:3].lower() in _MONTH_ABBR:
        return int(m.group(2)), _MONTH_ABBR.index(m.group(1)[:3].lower()) + 1
    m = re.fullmatch(r"\s*(\d{1,2})[/.\-](\d{4})\s*", s) or re.fullmatch(r"\s*(\d{4})-(\d{1,2})\s*", s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        year, month = (b, a) if len(m.group(1)) <= 2 else (a, b)     # 07/2023 is month first, 2023-07 is year first
        if 1 <= month <= 12:
            return year, month
    return None


def _iso(s: str, kind: str) -> str | None:
    ym = _month_year(s)
    if kind == "month":
        if ym:
            return f"{ym[0]:04d}-{ym[1]:02d}"
        d = parse_date_value(s)
        return d.strftime("%Y-%m") if d else None
    d = parse_date_value(s)
    if d:
        return d.isoformat()
    return f"{ym[0]:04d}-{ym[1]:02d}-01" if ym else None


def shape_value(value, shape: dict) -> str:
    """The text to type into a box of this shape. Unchanged unless the box's shape calls for a different form."""
    s = str(value)
    kind = (shape.get("type") or "").lower()
    if kind in ("month", "date"):
        return _iso(s, kind) or s
    if _numerals_only(shape):
        return _plain_number(s.strip()) or s
    return s
