"""Units and time windows for fitting a fact's value to a field (used by facts.render / facts.answer)."""
from __future__ import annotations

import re
from datetime import date

_DAYS_PER = {"day": 1, "week": 7, "month": 30}
_WIN_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|to)?\s*(\d+(?:\.\d+)?)?\s*\+?\s*(day|week|month)s?", re.I)


def _window(opt):
    """'Immediately' -> (0, 0); 'Within 30 days' / 'less than 1 month' -> (0, 30); '1-2 months' -> (30, 60);
    '60+ days' / 'more than 2 months' -> (60, inf); '30 days' -> (30, 30). None = not a time window."""
    s = opt.lower()
    if re.search(r"\bimmediate", s):
        return (0.0, 0.0)
    m = _WIN_NUM.search(s)
    if not m:
        return None
    per = _DAYS_PER[m.group(3).lower()]
    a, b = float(m.group(1)) * per, float(m.group(2)) * per if m.group(2) else None
    if b is not None:
        return (a, b)
    if re.search(r"less than|within|up ?to|under|<|max", s):
        return (0.0, a)
    if re.search(r"more than|above|over|>|\+|or more|beyond", s):
        return (a, float("inf"))
    return (a, a)


def window_option(days, options):
    """A day count into time-window options (notice period -> 'Within 30 days'): the narrowest window holding it.
    Only when the options ARE windows (two or more parse); otherwise None and the normal fitting runs."""
    wins = [(o, w) for o in options if (w := _window(o))]
    if len(wins) < 2:
        return None
    holding = [(w[1] - w[0], o) for o, w in wins if w[0] <= days <= w[1]]
    return min(holding)[1] if holding else None


def fit_unit(value, ftype, today, text):
    """A days fact into a field that counts weeks or months; a date into a field that counts days (from today)."""
    if ftype == "days" and isinstance(value, (int, float)) and not re.search(r"\bdays?\b", text, re.I):
        for unit, per in (("week", 7), ("month", 30)):
            if re.search(rf"\b{unit}s?\b", text, re.I):
                return round(value / per, 1)
    if isinstance(value, date) and re.search(r"\bdays?\b", text, re.I) and not re.search(r"\b(date|dd|mm)\b", text, re.I):
        return float((value - today).days)
    return value
