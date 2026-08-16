"""Classify how a job is applied to, so the dashboard can show at a glance
which listings the one-click auto-fill will breeze through.

The TRUE apply mechanism is only known by opening the posting (the apply
button could be Easy-Apply, a company ATS, or a broken redirect). This is a
cheap heuristic from the fields we DO have — source + job_url — meant as an
at-a-glance signal, not a guarantee:

- ``kind``  : short machine label
- ``label`` : short human badge text
- ``fill``  : how reliably the auto-fill works — "easy" | "maybe" | "manual"
"""
from __future__ import annotations

import re

# Known applicant-tracking-system / company-careers hosts. A job_url on one of
# these is a real external ATS form (Litmus7-style) the fill handles well.
_ATS_HOST = re.compile(
    r"(?:^|//|\.)("
    r"greenhouse\.io|lever\.co|myworkdayjobs\.com|ashbyhq\.com|smartrecruiters\.com|"
    r"jobvite\.com|icims\.com|taleo\.net|successfactors\.|zohorecruit\.com|"
    r"darwinbox\.|bamboohr\.com|recruitee\.com|workable\.com|breezy\.hr|"
    r"jobs\.[a-z0-9-]+\.[a-z]|careers\.[a-z0-9-]+\.[a-z]|apply\.[a-z0-9-]+\.[a-z]|hire\.[a-z0-9-]+\.[a-z]"
    r")",
    re.I,
)

# Aggregators that always link OUT to the company's own site/ATS.
_LINKS_OUT = ("himalayas", "remoteok", "remotive")


def classify_apply_type(source, job_url):
    """Return ``{"kind", "label", "fill"}`` for a job. Never raises."""
    src = (source or "").lower()
    url = job_url or ""

    if _ATS_HOST.search(url):
        return {"kind": "external-ats", "label": "ATS form", "fill": "easy"}
    if any(a in src for a in _LINKS_OUT):
        return {"kind": "company-site", "label": "Company site", "fill": "easy"}
    if "linkedin" in src:
        # Easy-Apply (fillable when logged in) OR an external redirect — mixed.
        return {"kind": "linkedin", "label": "LinkedIn", "fill": "maybe"}
    if "wellfound" in src:
        return {"kind": "wellfound", "label": "Wellfound", "fill": "maybe"}
    if "indeed" in src:
        return {"kind": "indeed", "label": "Indeed", "fill": "maybe"}
    if "naukri" in src:
        # Native apply (one-click / chatbot) or an often-broken company-site link.
        return {"kind": "naukri", "label": "Naukri", "fill": "manual"}
    return {"kind": "other", "label": src or "other", "fill": "manual"}
