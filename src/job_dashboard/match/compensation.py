"""Parse an annual CTC (in LPA — lakhs INR/year) from a job's messy salary text
or description, so the sweep can hide roles that state a package below a floor.

Deliberately CONSERVATIVE — returns ``None`` (unknown, don't hide) unless the
figure is confidently annual and parseable. Handles the real formats seen in the
data: "100000-150000 USD", "₹50L – ₹55L", "$150k - $230k", "25-35 LPA",
"₹30,000 – ₹35,000" (ambiguous → None), hourly (→ None), and "N LPA" in a JD
(but not "10 lakh users").
"""
from __future__ import annotations

import re

USD_TO_INR = 83.0

# Explicit "N LPA" / "N-M LPA" in free text — LPA token required so "10 lakh
# users" (revenue/scale, not pay) is NOT mistaken for a salary.
_JD_LPA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|to|–|—)?\s*(\d+(?:\.\d+)?)?\s*lpa\b", re.I)
# A number with an optional k / l(pa) / lakh suffix.
_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(k|lpa|lakhs?|lacs?|l)?", re.I)


def parse_ctc_lpa(salary_text):
    """Annual CTC upper-bound in LPA from a structured salary string, or None."""
    if not salary_text:
        return None
    raw = str(salary_text)
    t = raw.lower().replace(",", "").replace("–", "-").replace("—", "-")

    if any(h in t for h in ("/hour", "/hr", "per hour", "hourly", " ph")):
        return None  # hourly rate — not a comparable annual CTC

    is_usd = ("usd" in t) or ("$" in raw)
    monthly = (("month" in t or "/mo" in t or "p.m" in t)
               and not any(a in t for a in ("annum", "p.a", "lpa", "year", "/yr")))

    lpa_vals, amt_vals = [], []
    for num, suf in _NUM_RE.findall(t):
        if not num:
            continue
        n = float(num)
        suf = suf.lower()
        if suf in ("l", "lpa", "lakh", "lakhs", "lac", "lacs"):
            lpa_vals.append(n)          # already in lakhs/year
        elif suf == "k":
            amt_vals.append(n * 1000)
        else:
            amt_vals.append(n)

    if lpa_vals:
        return max(lpa_vals)            # explicit lakh notation — trust it
    if not amt_vals:
        return None

    hi = max(amt_vals)
    if is_usd:
        annual = hi * (12 if monthly else 1)
        lpa = annual * USD_TO_INR / 1e5
        return lpa if lpa >= 3 else None   # <3 LPA from USD ⇒ hourly/junk, skip
    if monthly:
        return hi * 12 / 1e5
    if hi >= 100000:                       # a 6+ digit annual rupee figure
        return hi / 1e5
    return None                            # small bare ₹ number → ambiguous, skip


def find_ctc_lpa_in_jd(description):
    """Max explicit 'N LPA' figure stated in a JD, or None. LPA token required."""
    if not description:
        return None
    vals = [float(b or a) for a, b in _JD_LPA_RE.findall(str(description))]
    return max(vals) if vals else None


def job_ctc_lpa(salary_text, description):
    """Best annual CTC (LPA) for a job: structured salary first, else an explicit
    'N LPA' in the JD. None when nothing reliable is stated."""
    return parse_ctc_lpa(salary_text) or find_ctc_lpa_in_jd(description)
